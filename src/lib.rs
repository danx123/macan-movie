use pyo3::prelude::*;
use pyo3::exceptions::{PyIOError, PyRuntimeError, PyValueError};
use pyo3::wrap_pyfunction;
use numpy::{IntoPyArray, PyArray1, PyArray3, ndarray::{Array1, Array3}};
use std::collections::VecDeque;
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU32, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use ringbuf::traits::{Consumer as _, Observer as _, Producer as _, Split as _};

// [BARU] rayon buat paralelkan komputasi envelope waveform & BPM detection
// (chunk-chunk independen -> gampang di-`par_iter()`-in, gak butuh thread
// pool manual). rustfft buat fungsi FFT visualizer (spectrum analyzer).
use rayon::prelude::*;
use rustfft::{Fft, FftPlanner, num_complex::Complex32};

// Alias biar gampang disesuaikan kalau nama tipe exact-nya beda dikit di
// versi `ringbuf` yang kepasang (API crate ini sempat berubah antar versi
// minor -- kalau compiler komplen "cannot find type HeapProd/HeapCons",
// cek `cargo doc --open -p ringbuf` terus ganti target alias di sini aja,
// gak perlu ubah kode pemakainya di bawah).
type AudioProducer = ringbuf::HeapProd<f32>;
type AudioConsumer = ringbuf::HeapCons<f32>;

// ═══════════════════════════════════════════════
// INISIALISASI FFmpeg (sekali saja saat dimuat)
// ═══════════════════════════════════════════════

fn init_ffmpeg() -> PyResult<()> {
    ffmpeg_next::init().map_err(|e| {
        PyRuntimeError::new_err(format!("Inisialisasi FFmpeg gagal: {}", e))
    })?;

    // [BARU] Wajib buat protokol jaringan (http/https/icecast dll) --
    // tanpa ini, `ffmpeg_next::format::input()` cuma bisa buka file lokal.
    // PlayerEngine (dipakai macan_radio.py buat stream radio & macan
    // audio player buat podcast) butuh ini biar bisa buka URL langsung.
    // avformat_network_init() sendiri aman dipanggil berkali-kali (FFmpeg
    // nge-refcount init-nya secara internal), jadi gak perlu guard tambahan
    // walau init_ffmpeg() ini kepanggil tiap kali PlayerEngine/MediaInfo/
    // AudioInfo baru dibikin.
    ffmpeg_next::format::network::init();

    Ok(())
}

// Input::seek() di ffmpeg-next dipanggil dengan stream_index = -1 di
// belakang layar (avformat_seek_file). Kalau stream_index = -1, FFmpeg
// nganggep timestamp yang dikasih dalam satuan AV_TIME_BASE (mikrodetik /
// 1_000_000), BUKAN time_base stream video. Dipakai di PlayerEngine
// (video/audio_decode_loop) MAUPUN VideoDecoder::seek_frame -- keduanya
// sama-sama manggil Input::seek() jadi sama-sama butuh konversi ini.
fn av_time_base_ts(seconds: f64) -> i64 {
    (seconds * 1_000_000.0) as i64
}

/// Konversi ffmpeg_next::Rational (time_base) ke f64 detik-per-tick.
/// Dipake di beberapa tempat yang butuh bandingin pts (dalam tick) ke
/// detik absolut (mis. trim di convert_media).
fn rational_to_f64(r: ffmpeg_next::Rational) -> f64 {
    if r.denominator() > 0 {
        r.numerator() as f64 / r.denominator() as f64
    } else {
        0.0
    }
}

// ═══════════════════════════════════════════════
// BAGIAN 1: INFORMASI MEDIA (gak diubah)
// ═══════════════════════════════════════════════

#[pyclass]
struct MediaInfo {
    #[pyo3(get)] path: String,
    #[pyo3(get)] duration: f64,
    #[pyo3(get)] width: u32,
    #[pyo3(get)] height: u32,
    #[pyo3(get)] fps: f64,
    #[pyo3(get)] codec: String,
    #[pyo3(get)] codec_id: String,
    #[pyo3(get)] bitrate: i64,
}

#[pymethods]
impl MediaInfo {
    #[new]
    fn new(file_path: &str) -> PyResult<Self> {
        init_ffmpeg()?;

        let path = Path::new(file_path);
        let input = ffmpeg_next::format::input(&path)
            .map_err(|e| PyIOError::new_err(format!("Buka file: {}", e)))?;

        let stream = input.streams()
            .best(ffmpeg_next::media::Type::Video)
            .ok_or_else(|| PyValueError::new_err("Tidak ada aliran video"))?;

        let id = stream.parameters().id();
        let codec_id = id.name().to_string();
        let codec = ffmpeg_next::codec::decoder::find(id)
            .map(|c| c.description().to_string())
            .unwrap_or_else(|| "Tidak diketahui".to_string());

        let fps = stream.avg_frame_rate();
        let fps = if fps.denominator() > 0 {
            fps.numerator() as f64 / fps.denominator() as f64
        } else { 0.0 };

        let duration = stream.duration() as f64 * f64::from(stream.time_base());
        let bitrate = input.bit_rate() as i64;

        let ctx = ffmpeg_next::codec::context::Context::from_parameters(stream.parameters())
            .map_err(|e| PyRuntimeError::new_err(format!("Konteks dekoder: {}", e)))?;

        let (width, height) = match ctx.decoder().video() {
            Ok(vdec) => (vdec.width(), vdec.height()),
            Err(_) => (0, 0),
        };

        Ok(MediaInfo {
            path: file_path.to_string(),
            duration, width, height, fps, codec, codec_id, bitrate,
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "MediaInfo(dur={:.2}s, {}x{} @{:.2}fps, {}, {} bitrate={}bps)",
            self.duration, self.width, self.height, self.fps, self.codec_id, self.codec, self.bitrate
        )
    }
}

// [BARU] Metadata stream AUDIO (codec/sample-rate/channels/bitrate), baca
// dari header file doang -- gak decode sample apapun. Sengaja dipisah dari
// MediaInfo (yang cuma probe stream video) drpd nambahin field audio ke
// situ, biar caller yang cuma butuh video (mis. VideoDecoder/seek_frame)
// gak ikut kena biaya probe stream audio yang gak dia pakai.
//
// Dipakai buat gantiin subprocess `ffprobe` di panel Properties Macan
// Video Player (lihat _PropertiesMetaWorker._probe_audio_info di
// macan_context.py) -- ffprobe punya timeout sampai 8 detik dan nge-spawn
// proses baru tiap panggilan, AudioInfo baca langsung dari header lewat
// binding yang udah ke-link di proses yang sama.
#[pyclass]
struct AudioInfo {
    #[pyo3(get)] path: String,
    #[pyo3(get)] duration: f64,
    #[pyo3(get)] codec: String,
    #[pyo3(get)] codec_id: String,
    #[pyo3(get)] sample_rate: u32,
    #[pyo3(get)] channels: u32,
    #[pyo3(get)] bitrate: i64,
}

#[pymethods]
impl AudioInfo {
    #[new]
    fn new(file_path: &str) -> PyResult<Self> {
        init_ffmpeg()?;

        let path = Path::new(file_path);
        let input = ffmpeg_next::format::input(&path)
            .map_err(|e| PyIOError::new_err(format!("Buka file: {}", e)))?;

        let stream = input.streams()
            .best(ffmpeg_next::media::Type::Audio)
            .ok_or_else(|| PyValueError::new_err("Tidak ada aliran audio"))?;

        let id = stream.parameters().id();
        let codec_id = id.name().to_string();
        let codec = ffmpeg_next::codec::decoder::find(id)
            .map(|c| c.description().to_string())
            .unwrap_or_else(|| "Tidak diketahui".to_string());

        // [BARU] Durasi -- diambil dari stream audio dulu (pola sama kayak
        // MediaInfo buat video), lalu fallback ke durasi container
        // (`input.duration()`, satuan AV_TIME_BASE/mikrodetik) kalau
        // per-stream-nya gak ke-isi (kejadian di beberapa format kayak MP3
        // CBR tanpa header durasi eksplisit per-stream). Dipakai gantiin
        // subprocess `ffprobe` di audio_cutter.py/advanced_tag_editorv87.py
        // (lihat _ffprobe_duration) -- baca langsung dari header lewat
        // binding yang udah ke-link di proses yang sama, bukan ffprobe
        // yang di-timeout sampai 8 detik dan nge-spawn proses baru.
        let tb = stream.time_base();
        let tb_f64 = if tb.denominator() > 0 { tb.numerator() as f64 / tb.denominator() as f64 } else { 0.0 };
        let stream_duration = stream.duration() as f64 * tb_f64;
        let duration = if stream_duration > 0.0 {
            stream_duration
        } else {
            (input.duration() as f64 / 1_000_000.0).max(0.0)
        };

        let ctx = ffmpeg_next::codec::context::Context::from_parameters(stream.parameters())
            .map_err(|e| PyRuntimeError::new_err(format!("Konteks dekoder: {}", e)))?;

        let adec = ctx.decoder().audio()
            .map_err(|e| PyRuntimeError::new_err(format!("Buat dekoder audio: {}", e)))?;

        let sample_rate = adec.rate();
        let channels = adec.channels() as u32;

        // [FIX] `codec::context::Context` (si `ctx` sebelum `.decoder()`) gak
        // punya method `bit_rate()` di ffmpeg-next 7.x -- itu cuma exist di
        // `codec::decoder::Opened` (lewat Deref-nya `Audio`/`Video`), jadi
        // HARUS dibaca dari `adec` di sini, SETELAH decoder-nya jadi, bukan
        // dari `ctx` sebelum `.decoder()` seperti sebelumnya.
        let ctx_bitrate = adec.bit_rate() as i64;

        // Fallback ke bitrate container kalau per-stream-nya gak ke-isi
        // (kejadian di beberapa container/codec yang gak nyimpen bit_rate
        // eksplisit di codec parameters-nya).
        let bitrate = if ctx_bitrate > 0 { ctx_bitrate } else { input.bit_rate() };

        Ok(AudioInfo {
            path: file_path.to_string(),
            duration, codec, codec_id, sample_rate, channels, bitrate,
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "AudioInfo(dur={:.2}s, {}, {} {}Hz {}ch, bitrate={}bps)",
            self.duration, self.codec_id, self.codec, self.sample_rate, self.channels, self.bitrate
        )
    }
}

// ═══════════════════════════════════════════════
// BAGIAN 2: DEKODER BINGKAI TUNGGAL (dipertahankan apa adanya
// untuk kebutuhan seek-frame / thumbnail. Player beneran pakai
// PlayerEngine di bawah.)
// ═══════════════════════════════════════════════

#[pyclass(unsendable)]
struct VideoDecoder {
    input_ctx: ffmpeg_next::format::context::Input,
    stream_idx: usize,
    decoder: ffmpeg_next::decoder::Video,
    scaler: Option<ffmpeg_next::software::scaling::Context>,
    time_base: f64,
    #[pyo3(get)] duration: f64,
    #[pyo3(get)] width: u32,
    #[pyo3(get)] height: u32,
    #[pyo3(get)] codec: String,
}

#[pymethods]
impl VideoDecoder {
    #[new]
    fn new(file_path: &str) -> PyResult<Self> {
        init_ffmpeg()?;
        let path = Path::new(file_path);
        let input_ctx = ffmpeg_next::format::input(&path)
            .map_err(|e| PyIOError::new_err(format!("Buka file: {}", e)))?;

        let stream = input_ctx.streams()
            .best(ffmpeg_next::media::Type::Video)
            .ok_or_else(|| PyValueError::new_err("Tidak ada aliran video"))?;
        let stream_idx = stream.index();

        let tb = stream.time_base();
        let time_base = if tb.denominator() > 0 {
            tb.numerator() as f64 / tb.denominator() as f64
        } else { 0.0 };

        let duration = stream.duration() as f64 * time_base;
        let codec = stream.parameters().id().name().to_string();

        let ctx = ffmpeg_next::codec::context::Context::from_parameters(stream.parameters())
            .map_err(|e| PyRuntimeError::new_err(format!("Konteks dekoder: {}", e)))?;
        let decoder = ctx.decoder().video()
            .map_err(|e| PyRuntimeError::new_err(format!("Buat dekoder: {}", e)))?;

        let (width, height) = (decoder.width(), decoder.height());

        Ok(VideoDecoder {
            input_ctx, stream_idx, decoder, scaler: None, time_base, duration, width, height, codec,
        })
    }

    fn seek_frame(&mut self, py: Python<'_>, second: f64) -> PyResult<Py<PyArray3<u8>>> {
        // BUG LAMA (sekarang dibenerin): input_ctx.seek() di ffmpeg-next
        // manggil avformat_seek_file dengan stream_index = -1 di baliknya,
        // yang artinya timestamp yang dikasih ke seek() itu HARUS dalam
        // satuan AV_TIME_BASE (mikrodetik / 1_000_000), BUKAN time_base
        // stream video. Sebelumnya kode ini pakai `second / self.time_base`
        // buat DUA hal sekaligus (parameter seek() DAN pembanding
        // decoded.timestamp()) -- padahal keduanya butuh satuan yang beda.
        // Efeknya: seek() lompat ke posisi yang salah total di file (bisa
        // jauh sebelum/sesudah yang dimaksud tergantung time_base-nya),
        // terus loop pencarian di bawah gagal nemuin frame yang match dalam
        // 200 paket -> "Bingkai tidak ditemukan". target_ts (buat
        // dibandingin ke decoded.timestamp()) tetep harus di time_base
        // stream, itu gak berubah -- yang salah cuma parameter ke seek().
        let seek_ts = av_time_base_ts(second);
        let target_ts = (second / self.time_base).round() as i64;
        self.input_ctx.seek(seek_ts, ..seek_ts)
            .map_err(|e| PyRuntimeError::new_err(format!("Lompat gagal: {}", e)))?;
        self.decoder.flush();

        let mut decoded = ffmpeg_next::frame::Video::empty();
        let mut packet_count = 0;
        let max_try = 200;
        let mut got_frame = false;

        'read_loop: for (stream, packet) in self.input_ctx.packets() {
            if packet_count > max_try {
                return Err(PyRuntimeError::new_err("Bingkai tidak ditemukan"));
            }
            if stream.index() != self.stream_idx {
                packet_count += 1;
                continue;
            }
            self.decoder.send_packet(&packet)
                .map_err(|e| PyRuntimeError::new_err(format!("Kirim paket gagal: {}", e)))?;
            while self.decoder.receive_frame(&mut decoded).is_ok() {
                got_frame = true;
                if decoded.timestamp().unwrap_or(0) >= target_ts {
                    break 'read_loop;
                }
            }
            packet_count += 1;
        }

        if !got_frame {
            return Err(PyRuntimeError::new_err("Tidak dapat membaca bingkai"));
        }

        rgb_from_decoded(py, &decoded, &mut self.scaler, self.decoder.format(), self.width, self.height)
    }

    fn read_next_frame(&mut self, py: Python<'_>) -> PyResult<Py<PyArray3<u8>>> {
        let mut decoded = ffmpeg_next::frame::Video::empty();
        let mut got_frame = false;

        for (stream, packet) in self.input_ctx.packets() {
            if stream.index() != self.stream_idx { continue; }
            self.decoder.send_packet(&packet)
                .map_err(|e| PyRuntimeError::new_err(format!("Kirim paket: {}", e)))?;
            if self.decoder.receive_frame(&mut decoded).is_ok() {
                got_frame = true;
                break;
            }
        }

        if !got_frame {
            return Err(PyRuntimeError::new_err("Akhir video"));
        }

        rgb_from_decoded(py, &decoded, &mut self.scaler, self.decoder.format(), self.width, self.height)
    }
}

/// Helper bareng: konversi 1 frame YUV/dst hasil decode -> np.array RGB [H,W,3].
/// Dipisah dari VideoDecoder biar gak duplikat logic scaler+stride-strip.
fn rgb_from_decoded(
    py: Python<'_>,
    decoded: &ffmpeg_next::frame::Video,
    scaler_slot: &mut Option<ffmpeg_next::software::scaling::Context>,
    src_format: ffmpeg_next::util::format::Pixel,
    width: u32,
    height: u32,
) -> PyResult<Py<PyArray3<u8>>> {
    let scaler = match scaler_slot {
        Some(s) => s,
        None => {
            let ctx = ffmpeg_next::software::scaling::Context::get(
                src_format, width, height,
                ffmpeg_next::util::format::Pixel::RGB24, width, height,
                ffmpeg_next::software::scaling::flag::Flags::BILINEAR,
            ).map_err(|e| PyRuntimeError::new_err(format!("Buat konteks scaling: {}", e)))?;
            scaler_slot.insert(ctx)
        }
    };

    let mut rgb_frame = ffmpeg_next::frame::Video::new(
        ffmpeg_next::util::format::Pixel::RGB24, width, height,
    );
    scaler.run(decoded, &mut rgb_frame)
        .map_err(|e| PyRuntimeError::new_err(format!("Konversi warna gagal: {}", e)))?;

    let stride = rgb_frame.stride(0);
    let row_width = (width as usize) * 3;
    let mut data = Vec::with_capacity((height as usize) * row_width);
    let raw_data = rgb_frame.data(0);
    for y in 0..(height as usize) {
        let start = y * stride;
        data.extend_from_slice(&raw_data[start..start + row_width]);
    }

    let arr = Array3::from_shape_vec((height as usize, width as usize, 3), data)
        .map_err(|e| PyRuntimeError::new_err(format!("Array gagal: {}", e)))?;
    Ok(arr.into_pyarray(py).into())
}

// ═══════════════════════════════════════════════
// BAGIAN 3: PLAYER ENGINE — decode+audio jalan di thread sendiri,
// audio dipakai sebagai master clock, video di-sync ke clock itu.
// ═══════════════════════════════════════════════

struct QueuedFrame {
    rgb: Vec<u8>,
    pts: f64, // detik
}

/// State yang dishare antara thread decode dan method Python.
/// Semua field pakai atomic/Mutex karena diakses dari 2 thread.
struct Shared {
    video_q: Mutex<VecDeque<QueuedFrame>>,

    // Buffer sample audio SENDIRI (bukan di sini) -- itu ring buffer
    // lock-free (`ringbuf`) yang producer-nya dipegang decode thread dan
    // consumer-nya dipegang callback cpal, gak lewat Shared/Mutex sama
    // sekali. Dulu di sini ada `audio_buf: Mutex<VecDeque<f32>>`, tapi
    // Mutex yang dikunci dari REAL-TIME audio callback itu rawan glitch:
    // begitu decode thread lagi megang lock buat nge-`extend()` (apalagi
    // pas VecDeque kebetulan perlu realokasi), callback bisa ke-delay
    // ngelewatin deadline periode audio device -> kedengeran kresek/glitch.
    // Ring buffer SPSC gak butuh lock sama sekali buat push/pop, jadi
    // masalah ini ilang di akarnya.
    audio_buffered_hint: AtomicUsize, // isi ring buffer sample, diupdate decode thread abis tiap push

    // [BARU] Snapshot sample audio TERBARU (mono, sudah di-downmix), khusus
    // buat FFT visualizer (get_spectrum). Sengaja DIPISAH dari ring buffer
    // playback (`AudioProducer`/`AudioConsumer` di atas) -- itu SPSC dan
    // sample-nya HABIS begitu dikonsumsi callback cpal (gak bisa "diintip"
    // tanpa ganggu playback). viz_ring ini cuma buat baca-baca (nampilin
    // bar spectrum), jadi dipush terus ditulis-timpa (bounded), BUKAN
    // dikonsumsi/di-pop kayak ring buffer audio asli.
    viz_ring: Mutex<VecDeque<f32>>,
    // One-shot flag: "buang semua sample yg lagi ngendon di ring buffer
    // SEBELUM lanjut konsumsi normal". Di-set true dari reset_clock() (jadi
    // otomatis kepasang tiap ada seek/step/loop-restart), dibaca & di-reset
    // ke false sekali sama audio callback. AMAN dipasang dari decode thread
    // karena producer gak bisa "clear" ring buffer-nya sendiri (yang megang
    // posisi baca itu consumer, hidup di thread audio) -- jadi sinyal ini
    // yang nyuruh consumer-nya sendiri yang beresin.
    audio_flush: AtomicBool,

    // Jumlah "sample frame" (bukan float individual) yang udah beneran
    // dibunyikan lewat callback cpal -> ini jadi master clock kalau ada audio.
    audio_frames_played: AtomicU64,
    out_sample_rate: AtomicI64,
    out_channels: AtomicI64,
    has_audio: AtomicBool,

    // f32 disimpen lewat to_bits()/from_bits() karena gak ada AtomicF32 di
    // std. 1.0 = full volume, 0.0 = diam. muted dipisah dari volume biar
    // toggle mute gak ngerusak nilai volume sebelumnya (bisa balik ke
    // volume yg sama pas di-unmute).
    volume_bits: AtomicU32,
    muted: AtomicBool,

    // Mekanisme seek pakai "generation counter", BUKAN Option<f64> yang
    // di-`take()` -- itu cuma bisa dikonsumsi SEKALI sama SATU pembaca.
    // Sekarang ada 2 thread decode (video & audio) yang masing-masing
    // butuh tau ada seek baru & ngerjain seek versi mereka sendiri (buka
    // file handle sendiri-sendiri) -- generation counter bikin keduanya
    // bisa independen ngecek "apa ada seek yang belom gue apply?" tanpa
    // rebutan konsumsi satu sinyal yang sama.
    seek_seq: AtomicU64,
    seek_target: Mutex<f64>,

    playing: AtomicBool,
    stop: AtomicBool,
    eof: AtomicBool,

    // Auto-restart dari awal kalau nyampe EOF.
    loop_enabled: AtomicBool,
    // Sinyal one-shot ke decode thread: "decode & tampilin SATU frame video
    // lagi walopun lagi paused". Dipakai buat frame-step (scrubbing per-frame).
    step_request: AtomicBool,

    // Basis clock: pts pemutaran dimulai dari sini + (waktu berjalan sejak play()).
    // Dipakai kalau video tanpa audio, atau sebelum audio callback mulai jalan.
    clock_base_pts: Mutex<f64>,
    clock_base_wall: Mutex<Option<Instant>>,
}

impl Shared {
    fn position(&self) -> f64 {
        if self.has_audio.load(Ordering::Relaxed) {
            let sr = self.out_sample_rate.load(Ordering::Relaxed).max(1) as f64;
            let base = *self.clock_base_pts.lock().unwrap();
            let frames = self.audio_frames_played.load(Ordering::Relaxed) as f64;
            base + frames / sr
        } else {
            let base = *self.clock_base_pts.lock().unwrap();
            match *self.clock_base_wall.lock().unwrap() {
                Some(t) if self.playing.load(Ordering::Relaxed) => {
                    base + t.elapsed().as_secs_f64()
                }
                _ => base,
            }
        }
    }

    /// Volume yang beneran dipakai di audio callback: 0 kalau lagi muted,
    /// selain itu ya volume_bits apa adanya.
    fn effective_volume(&self) -> f32 {
        if self.muted.load(Ordering::Relaxed) {
            0.0
        } else {
            f32::from_bits(self.volume_bits.load(Ordering::Relaxed))
        }
    }

    /// Bekukan clock di posisi sekarang TANPA nge-flush ring buffer audio.
    /// Dipakai buat pause() -- beda sama seek/step, pause itu bukan
    /// diskontinuitas timeline, buffer readahead yang udah kebentuk masih
    /// 100% valid buat dilanjutin pas resume, jadi jangan dibuang.
    fn freeze_clock(&self, pts: f64) {
        *self.clock_base_pts.lock().unwrap() = pts;
        *self.clock_base_wall.lock().unwrap() = Some(Instant::now());
        self.audio_frames_played.store(0, Ordering::Relaxed);
    }

    /// Reset clock ke titik waktu tertentu KARENA timeline abis loncat:
    /// seek manual, frame-step, atau auto-restart loop. Beda sama
    /// freeze_clock(), ini JUGA nge-flush ring buffer audio -- sample lama
    /// yg masih ngendon di situ udah gak valid lagi buat posisi baru ini.
    fn reset_clock(&self, pts: f64) {
        self.freeze_clock(pts);
        self.audio_flush.store(true, Ordering::Relaxed);
        self.audio_buffered_hint.store(0, Ordering::Relaxed);
    }
}

const MAX_VIDEO_FRAMES: usize = 90; // ~3 detik @30fps, batas memori readahead
const LATE_FRAME_DROP_SEC: f64 = 0.1; // frame yg telat >100ms dianggap basi

// [BARU] Kapasitas viz_ring (jumlah sample mono). 8192 cukup buat FFT
// visualizer sampe fft_size besar (mis. 4096) sambil nyisain sedikit
// headroom, tanpa nyimpen histori kepanjangan (gak butuh detik-detik lalu,
// cuma "sesaat sebelum sekarang" buat digambar tiap frame UI).
const VIZ_RING_CAP: usize = 8192;

#[pyclass(unsendable)]
struct PlayerEngine {
    shared: Arc<Shared>,
    video_thread: Option<JoinHandle<()>>,
    audio_thread: Option<JoinHandle<()>>,
    _audio_stream: Option<cpal::Stream>, // harus tetep hidup selama playback
    #[pyo3(get)] duration: f64,
    #[pyo3(get)] width: u32,
    #[pyo3(get)] height: u32,
    #[pyo3(get)] fps: f64,
    #[pyo3(get)] has_audio: bool,
    // [BARU] True kalau file punya stream video. Dulu PlayerEngine cuma bisa
    // dipakai buat file yang PASTI ada videonya (constructor gagal keras
    // kalau gak nemu stream video) -- itu bikin dia gak bisa dipakai buat
    // playback file AUDIO MURNI (mp3/flac/wav/dll) kayak yang dipakai
    // audio_cutter.py & advanced_tag_editorv87.py (dulu masih pakai
    // QMediaPlayer/QAudioOutput dari QtMultimedia buat kasus ini). Sekarang
    // video jadi opsional: kalau gak ada stream video, width/height/fps
    // dikosongin (0) dan has_video = false, TAPI decode+playback AUDIO
    // tetep jalan normal lewat audio_decode_loop() seperti biasa.
    #[pyo3(get)] has_video: bool,
}

#[pymethods]
impl PlayerEngine {
    #[new]
    fn new(file_path: &str) -> PyResult<Self> {
        init_ffmpeg()?;

        let path = Path::new(file_path);
        let probe = ffmpeg_next::format::input(&path)
            .map_err(|e| PyIOError::new_err(format!("Buka file: {}", e)))?;

        // [BARU] Video sekarang OPSIONAL. video_decode_loop() (BAGIAN 3)
        // sendiri udah aman dipanggil buat file tanpa video sama sekali --
        // dia `return` langsung begitu gak nemu stream video (lihat awal
        // fungsinya), jadi thread video-nya idle/exit cepat tanpa ganggu
        // apapun. Yang HARUS diubah di sini cuma bagian probe metadata
        // (duration/width/height/fps), yang sebelumnya wajib ambil dari
        // stream video dan bakal gagal keras (`ok_or_else` -> Err) kalau
        // stream itu gak ada.
        let vstream_opt = probe.streams().best(ffmpeg_next::media::Type::Video);
        let has_video = vstream_opt.is_some();
        let mut duration = 0.0f64;
        let mut width = 0u32;
        let mut height = 0u32;
        let mut fps = 0.0f64;

        if let Some(vstream) = vstream_opt {
            let vtb = vstream.time_base();
            let vtb = if vtb.denominator() > 0 { vtb.numerator() as f64 / vtb.denominator() as f64 } else { 0.0 };
            duration = vstream.duration() as f64 * vtb;
            fps = {
                let f = vstream.avg_frame_rate();
                if f.denominator() > 0 { f.numerator() as f64 / f.denominator() as f64 } else { 30.0 }
            };
            let vctx = ffmpeg_next::codec::context::Context::from_parameters(vstream.parameters())
                .map_err(|e| PyRuntimeError::new_err(format!("Konteks dekoder video: {}", e)))?;
            let vdec_probe = vctx.decoder().video()
                .map_err(|e| PyRuntimeError::new_err(format!("Buat dekoder video: {}", e)))?;
            width = vdec_probe.width();
            height = vdec_probe.height();
            drop(vdec_probe);
        }

        let has_audio = probe.streams().best(ffmpeg_next::media::Type::Audio).is_some();

        // [BARU] File audio murni (gak ada stream video sama sekali): durasi
        // gak bisa diambil dari stream video (gak ada), jadi diambil dari
        // stream audio -- pola sama kayak AudioInfo::new() (BAGIAN 1):
        // durasi per-stream dulu, fallback ke durasi container kalau
        // per-stream-nya gak ke-isi.
        if !has_video {
            if let Some(astream) = probe.streams().best(ffmpeg_next::media::Type::Audio) {
                let atb = astream.time_base();
                let atb = if atb.denominator() > 0 { atb.numerator() as f64 / atb.denominator() as f64 } else { 0.0 };
                let astream_duration = astream.duration() as f64 * atb;
                duration = if astream_duration > 0.0 {
                    astream_duration
                } else {
                    (probe.duration() as f64 / 1_000_000.0).max(0.0)
                };
            }
        }

        // File gak punya video MAUPUN audio -- gak ada apa-apa buat diputer.
        if !has_video && !has_audio {
            return Err(PyValueError::new_err("Tidak ada aliran video atau audio yang bisa diputar"));
        }

        drop(probe);

        let shared = Arc::new(Shared {
            video_q: Mutex::new(VecDeque::new()),
            audio_buffered_hint: AtomicUsize::new(0),
            viz_ring: Mutex::new(VecDeque::with_capacity(VIZ_RING_CAP)),
            audio_flush: AtomicBool::new(false),
            audio_frames_played: AtomicU64::new(0),
            out_sample_rate: AtomicI64::new(48000),
            out_channels: AtomicI64::new(2),
            has_audio: AtomicBool::new(has_audio),
            volume_bits: AtomicU32::new(1.0f32.to_bits()),
            muted: AtomicBool::new(false),
            seek_seq: AtomicU64::new(0),
            seek_target: Mutex::new(0.0),
            playing: AtomicBool::new(false),
            stop: AtomicBool::new(false),
            eof: AtomicBool::new(false),
            loop_enabled: AtomicBool::new(false),
            step_request: AtomicBool::new(false),
            clock_base_pts: Mutex::new(0.0),
            clock_base_wall: Mutex::new(None),
        });

        // ── Setup cpal output stream (kalau ada audio) ──
        // Callback ini jalan di audio thread milik OS (real-time), jadi
        // JANGAN pernah block lama di sini. Buffer sample-nya pakai ring
        // buffer SPSC lock-free (`ringbuf`), bukan Mutex<VecDeque> -- Mutex
        // yang dikunci dari sini rawan bikin glitch kalau decode thread
        // kebetulan lagi megang lock pas callback butuh jalan (apalagi kalau
        // sampe ada realokasi Vec di baliknya).
        let mut audio_stream: Option<cpal::Stream> = None;
        let mut audio_producer: Option<AudioProducer> = None;
        if has_audio {
            let host = cpal::default_host();
            if let Some(device) = host.default_output_device() {
                if let Ok(cfg) = device.default_output_config() {
                    let sample_rate = cfg.sample_rate().0 as i64;
                    let channels = cfg.channels() as i64;
                    shared.out_sample_rate.store(sample_rate, Ordering::Relaxed);
                    shared.out_channels.store(channels, Ordering::Relaxed);

                    // ~3 detik headroom -- lebih gede dikit drpd batas
                    // backpressure (a_cap, ~2 detik di decode thread) biar
                    // producer nyaris gak pernah kejadian nabrak penuh.
                    let capacity = ((sample_rate as usize) * (channels as usize) * 3).max(4096);
                    let rb = ringbuf::HeapRb::<f32>::new(capacity);
                    let (producer, mut consumer): (AudioProducer, AudioConsumer) = rb.split();

                    let stream_cfg: cpal::StreamConfig = cfg.clone().into();
                    let shared_cb = Arc::clone(&shared);

                    let build_result = match cfg.sample_format() {
                        cpal::SampleFormat::F32 => device.build_output_stream(
                            &stream_cfg,
                            move |data: &mut [f32], _| {
                                if shared_cb.audio_flush.swap(false, Ordering::Relaxed) {
                                    // Timeline abis loncat (seek/step/loop-restart) --
                                    // buang semua sample LAMA yg masih ngendon
                                    // sebelum lanjut konsumsi normal. Tanpa ini,
                                    // abis seek bakal kedengeran "kilas balik"
                                    // sepersekian detik audio dari posisi lama.
                                    while consumer.try_pop().is_some() {}
                                }
                                let ch = shared_cb.out_channels.load(Ordering::Relaxed).max(1) as usize;
                                // Dibaca sekali per callback (bukan per-sample) biar gak ada
                                // atomic load ribuan kali per buffer -- toh kuping gak bakal
                                // notice volume berubah di tengah satu buffer (~ms doang).
                                let vol = shared_cb.effective_volume();
                                for sample in data.iter_mut() {
                                    // 0.0 = diam kalau buffer kosong (underrun)
                                    *sample = consumer.try_pop().unwrap_or(0.0) * vol;
                                }
                                // Frame count buat clock TETEP dihitung dari data yang
                                // dikonsumsi apa adanya -- volume/mute gak boleh ganggu
                                // sinkronisasi audio-video.
                                shared_cb.audio_frames_played.fetch_add((data.len() / ch) as u64, Ordering::Relaxed);
                            },
                            |err| eprintln!("[media_engine] audio stream error: {err}"),
                            None,
                        ),
                        // Device jarang minta selain f32 di WASAPI shared mode,
                        // tapi kalau ketemu kasusnya, tambahin cabang i16/u16 di sini.
                        _ => Err(cpal::BuildStreamError::StreamConfigNotSupported),
                    };

                    if let Ok(stream) = build_result {
                        // JANGAN langsung .play() di sini. Kalau langsung jalan,
                        // callback di atas bakal langsung mulai narik ring buffer
                        // yang masih kosong (decode thread belom sempet ngisi
                        // apa2), dan tetep nambah audio_frames_played walopun
                        // yang keluar cuma silence-filler. Efeknya: clock udah
                        // "maju" duluan sebelum ada suara asli yang kebunyi,
                        // dan video bakal ngerasa harus ngejar dari awal --
                        // persis gejala "video-audio kerasa ada jeda" yang
                        // nempel terus sepanjang playback. Stream ini baru
                        // beneran di-play() pas play()/seek() Python dipanggil,
                        // sesudah buffer di-priming (lihat wait_for_seek_ready).
                        let _ = stream.pause();
                        audio_stream = Some(stream);
                        audio_producer = Some(producer);
                    } else {
                        // Gagal setup audio device -> tetep jalan sebagai video-only,
                        // jangan gagalin seluruh player gara-gara audio device bermasalah.
                        shared.has_audio.store(false, Ordering::Relaxed);
                    }
                } else {
                    shared.has_audio.store(false, Ordering::Relaxed);
                }
            } else {
                shared.has_audio.store(false, Ordering::Relaxed);
            }
        }

        let final_has_audio = shared.has_audio.load(Ordering::Relaxed);

        // ── Spawn thread video & audio TERPISAH ──
        // Ini kunci fix-nya: dulu satu thread ngurusin demux+decode video
        // DAN audio bareng, gantian satu paket per iterasi. Begitu video
        // kena beban berat (keyframe gede, atau abis seek yang butuh
        // "ngejar" dari keyframe terdekat ke posisi target), audio ikut
        // ke-block nungguin gantian -- ring buffer-nya gak ke-isi selama
        // itu -> underrun/glitch. Dengan 2 thread + 2 file handle sendiri,
        // video yang lagi berat gak akan pernah bisa mem-block audio lagi.
        let video_shared = Arc::clone(&shared);
        let video_path = file_path.to_string();
        let video_thread = thread::Builder::new()
            .name("media_engine-video".into())
            .spawn(move || video_decode_loop(video_path, video_shared))
            .map_err(|e| PyRuntimeError::new_err(format!("Spawn thread video gagal: {}", e)))?;

        let audio_thread = if let Some(producer) = audio_producer {
            let audio_shared = Arc::clone(&shared);
            let audio_path = file_path.to_string();
            Some(
                thread::Builder::new()
                    .name("media_engine-audio".into())
                    .spawn(move || audio_decode_loop(audio_path, audio_shared, producer))
                    .map_err(|e| PyRuntimeError::new_err(format!("Spawn thread audio gagal: {}", e)))?,
            )
        } else {
            None
        };

        Ok(PlayerEngine {
            shared,
            video_thread: Some(video_thread),
            audio_thread,
            _audio_stream: audio_stream,
            duration,
            width,
            height,
            fps,
            has_audio: final_has_audio,
            has_video,
        })
    }

    /// Mulai/lanjutkan playback.
    fn play(&mut self) {
        if !self.shared.playing.swap(true, Ordering::SeqCst) {
            // Tunggu AUDIO dan VIDEO dua2nya siap sebelum stream cpal
            // beneran dibuka. Lihat wait_for_seek_ready() -- ini juga yang
            // nyegah audio "kabur duluan" ninggalin video pas video masih
            // proses nyiapin frame pertama.
            let target = self.shared.position();
            self.wait_for_seek_ready(target);
            if let Some(stream) = self._audio_stream.as_ref() {
                let _ = stream.play();
            }
            *self.shared.clock_base_wall.lock().unwrap() = Some(Instant::now());
        }
    }

    /// Jeda playback. Ini nge-freeze SEMUANYA: decode thread berhenti baca
    /// paket baru, DAN stream audio cpal-nya beneran di-pause (bukan cuma
    /// decode-nya doang) -- kalau ini kelewat, sisa buffer readahead (~2
    /// detik) bakal tetep kebunyi & bikin clock (makanya seekbar) keliatan
    /// jalan terus meski status-nya "paused".
    fn pause(&mut self) {
        if let Some(stream) = self._audio_stream.as_ref() {
            let _ = stream.pause();
        }
        // PENTING: pakai freeze_clock() (bukan reset_clock()) -- pause itu
        // BUKAN diskontinuitas timeline kayak seek, buffer readahead yang
        // udah kebentuk masih valid buat dilanjutin pas resume, jangan
        // sampe ke-flush. Yang WAJIB tetep dilakuin cuma nge-nolin
        // audio_frames_played bareng base -- kalau frames_played dibiarin
        // jalan terus dari angka lama sementara base udah "menyerap" nilai
        // lama itu juga, position() = base + frames/sr bakal DOBEL-ngitung
        // waktu yang sama tiap siklus pause->resume -- position() jadi jauh
        // melenceng dari pts frame manapun di queue, semua frame video
        // keanggep "telat" dan didrop terus-terusan (video macet total),
        // sementara audio gak kena imbasnya sama sekali karena audio
        // callback gak pernah baca position(), dia cuma narik dari
        // buffernya sendiri.
        let pos = self.shared.position();
        self.shared.freeze_clock(pos);
        self.shared.playing.store(false, Ordering::SeqCst);
    }

    /// True kalau lagi playing (bukan paused/belum di-play sama sekali).
    fn is_playing(&self) -> bool {
        self.shared.playing.load(Ordering::Relaxed)
    }

    /// Hentikan playback & balikin posisi ke awal file (detik 0), freeze.
    /// Beda sama pause(): stop() juga nge-reset posisi, bukan cuma nahan
    /// di posisi sekarang.
    fn stop(&mut self) {
        self.pause();
        self.seek(0.0);
    }

    /// Nyalain/matiin auto-restart dari awal pas playback nyampe akhir file.
    fn set_loop(&mut self, enabled: bool) {
        self.shared.loop_enabled.store(enabled, Ordering::Relaxed);
    }

    fn is_looping(&self) -> bool {
        self.shared.loop_enabled.load(Ordering::Relaxed)
    }

    /// Maju SATU frame video. Cuma masuk akal dipanggil pas lagi paused --
    /// kalau lagi playing, ini gak ngapa2in (biar gak bentrok sama decode
    /// thread yang emang lagi jalan normal). Setelah dipanggil, tunggu 1-2
    /// tick lalu ambil hasilnya lewat get_frame() seperti biasa -- clock
    /// otomatis ikut digeser ke pts frame yang baru itu.
    fn step_frame(&mut self) {
        if !self.shared.playing.load(Ordering::Relaxed) {
            self.shared.step_request.store(true, Ordering::SeqCst);
        }
    }

    /// Lompat ke detik tertentu. Kalau lagi playing, audio stream dipause
    /// sesaat sementara nunggu KEDUANYA (audio dan video) siap lagi di
    /// posisi baru. Audio biasanya seek hampir instan, tapi video harus
    /// nyari keyframe terdekat dulu baru "ngejar" maju ke target -- itu
    /// bisa makan waktu jauh lebih lama drpd audio. Kalau cuma nunggu audio
    /// doang (seperti sebelumnya), begitu resume, audio langsung jalan dari
    /// posisi target sementara video masih proses ngejar -- kerasa "audio
    /// duluan drpd video". Kalau lagi paused, gak ada yang perlu ditunggu
    /// (stream emang udah diem, dan Python nunggu next tick apa adanya).
    fn seek(&mut self, second: f64) {
        let was_playing = self.shared.playing.load(Ordering::Relaxed);
        if was_playing {
            if let Some(stream) = self._audio_stream.as_ref() {
                let _ = stream.pause();
            }
        }

        self.shared.eof.store(false, Ordering::SeqCst);
        *self.shared.seek_target.lock().unwrap() = second;
        self.shared.seek_seq.fetch_add(1, Ordering::SeqCst);

        if was_playing {
            self.wait_for_seek_ready(second);
            if let Some(stream) = self._audio_stream.as_ref() {
                let _ = stream.play();
            }
        }
    }

    /// Posisi playback sekarang (detik), dihitung dari clock audio
    /// (atau wall-clock kalau video-only).
    fn position(&self) -> f64 {
        self.shared.position()
    }

    /// Atur volume 0.0 (diam) - 1.0 (full). Nilai di luar itu di-clamp,
    /// jadi aman dipanggil langsung dari slider Qt tanpa validasi tambahan.
    fn set_volume(&mut self, volume: f32) {
        let v = volume.clamp(0.0, 1.0);
        self.shared.volume_bits.store(v.to_bits(), Ordering::Relaxed);
    }

    fn get_volume(&self) -> f32 {
        f32::from_bits(self.shared.volume_bits.load(Ordering::Relaxed))
    }

    fn set_muted(&mut self, muted: bool) {
        self.shared.muted.store(muted, Ordering::Relaxed);
    }

    fn is_muted(&self) -> bool {
        self.shared.muted.load(Ordering::Relaxed)
    }

    fn is_eof(&self) -> bool {
        self.shared.eof.load(Ordering::Relaxed)
            && self.shared.video_q.lock().unwrap().is_empty()
    }

    /// Panggil ini tiap tick UI (misal tiap ~8-16ms). Balikin None kalau
    /// belum waktunya nampilin frame baru — di situasi itu Python cukup
    /// nampilin frame terakhir yang ada, jangan blok nunggu.
    /// Return: Some((array_rgb, pts_detik)) atau None.
    fn get_frame(&mut self, py: Python<'_>) -> PyResult<Option<(Py<PyArray3<u8>>, f64)>> {
        let now = self.shared.position();
        let mut q = self.shared.video_q.lock().unwrap();

        // Buang frame yang udah basi (telat) biar gak numpuk delay -> ini
        // yang bikin video "ngejar" balik ke posisi seharusnya kalau sempet
        // ketinggalan, dibanding numpuk dan diputer kayak fast-forward.
        while let Some(front) = q.front() {
            if front.pts + LATE_FRAME_DROP_SEC < now {
                q.pop_front();
                continue;
            }
            break;
        }

        let ready = matches!(q.front(), Some(f) if f.pts <= now);
        if !ready {
            return Ok(None);
        }
        let frame = q.pop_front().unwrap();
        drop(q);

        let arr = Array3::from_shape_vec(
            (self.height as usize, self.width as usize, 3),
            frame.rgb,
        ).map_err(|e| PyRuntimeError::new_err(format!("Array gagal: {}", e)))?;

        Ok(Some((arr.into_pyarray(py).into(), frame.pts)))
    }

    /// [BARU] FFT visualizer -- panggil ini tiap tick UI (bareng
    /// get_frame()) buat ngambil spektrum frekuensi dari audio yang LAGI
    /// dibunyikan saat ini. `fft_size` HARUS pangkat 2 (mis. 512/1024/2048),
    /// makin gede makin detail resolusi frekuensinya tapi makin berat.
    ///
    /// Balikin array magnitude dalam skala dB, panjang fft_size/2 (bin
    /// Nyquist ke atas dibuang karena buat sinyal real cuma cerminan bin
    /// bawahnya -- gak nambah info buat divisualisasikan).
    fn get_spectrum(&self, py: Python<'_>, fft_size: usize) -> PyResult<Py<PyArray1<f32>>> {
        if fft_size == 0 || (fft_size & (fft_size - 1)) != 0 {
            return Err(PyValueError::new_err("fft_size harus pangkat 2 (mis. 512, 1024, 2048)"));
        }

        // Ambil `fft_size` sample TERBARU dari viz_ring. Kalau belum cukup
        // (baru mulai play / lagi diam), padding nol di depan -- daripada
        // dilempar error tiap tick UI yang notabene bakal sering kejadian
        // pas awal playback.
        let samples: Vec<f32> = {
            let viz = self.shared.viz_ring.lock().unwrap();
            let have = viz.len();
            if have >= fft_size {
                viz.iter().skip(have - fft_size).copied().collect()
            } else {
                let mut v = vec![0.0f32; fft_size - have];
                v.extend(viz.iter().copied());
                v
            }
        };

        // Windowing (Hann) biar spektrum gak "bocor" (spectral leakage)
        // gara-gara motong sinyal secara tegas di tepi buffer.
        let mut buf: Vec<Complex32> = samples.iter().enumerate().map(|(i, &s)| {
            let w = 0.5 - 0.5 * (2.0 * std::f32::consts::PI * i as f32 / (fft_size - 1) as f32).cos();
            Complex32::new(s * w, 0.0)
        }).collect();

        let mut planner = FftPlanner::<f32>::new();
        let fft = planner.plan_fft_forward(fft_size);
        fft.process(&mut buf);

        let half = fft_size / 2;
        let norm = fft_size as f32;
        let spectrum: Vec<f32> = buf[..half].iter().map(|c| {
            let mag = c.norm() / norm;
            // dB, dikasih floor -120dB biar log(0) (sample diem total)
            // gak ngehasilin -inf yang bikin widget UI kacau pas digambar.
            20.0 * mag.max(1e-6).log10()
        }).collect();

        let arr = Array1::from_vec(spectrum);
        Ok(arr.into_pyarray(py).into())
    }

    /// Hentikan playback & kedua thread decode. Panggil eksplisit sebelum
    /// object di-drop kalau mau nutup lebih cepat / ganti file.
    fn close(&mut self) {
        self.shared.stop.store(true, Ordering::SeqCst);
        if let Some(h) = self.video_thread.take() {
            let _ = h.join();
        }
        if let Some(h) = self.audio_thread.take() {
            let _ = h.join();
        }
    }
}

/// Helper internal -- sengaja dipisah dari blok #[pymethods] di atas
/// biar gak ikut ke-expose sebagai method Python.
impl PlayerEngine {
    /// Tunggu (dibatasi ~400ms) sampe AUDIO dan VIDEO dua2nya siap di
    /// sekitar posisi `target`, sebelum stream audio beneran
    /// dibuka/dibuka-lagi. Dipanggil dari play() dan seek().
    ///
    /// - Audio dianggap siap kalau ring buffer-nya udah keisi ~150ms sample.
    /// - Video dianggap siap kalau frame TERBARU yang udah didecode
    ///   (q.back(), bukan q.front() -- back() nunjukkin sejauh mana decode
    ///   udah "nyampe", front() cuma frame paling lama yg masih ngendon)
    ///   udah nyampe/lewatin target. Video butuh ini krn abis seek dia
    ///   harus nyari keyframe dulu baru ngejar maju ke target -- proses itu
    ///   ambil waktu jauh lebih lama drpd audio yang seek-nya nyaris instan.
    ///
    /// Tanpa nunggu video juga, audio bakal mulai bunyi duluan begitu
    /// buffer-nya siap, ninggalin video yang masih proses ngejar -- kerasa
    /// "audio duluan drpd video" tiap abis play()/seek(). Timeout ada biar
    /// UI gak nge-hang selamanya kalau video-nya lambat/macet.
    fn wait_for_seek_ready(&self, target: f64) {
        let sr = self.shared.out_sample_rate.load(Ordering::Relaxed).max(1) as usize;
        let ch = self.shared.out_channels.load(Ordering::Relaxed).max(1) as usize;
        let audio_target = (sr * ch) / 7; // ~150ms readahead sebelum mulai bunyi
        let deadline = Instant::now() + Duration::from_millis(400);

        while Instant::now() < deadline {
            let audio_ready = !self.has_audio
                || self.shared.audio_buffered_hint.load(Ordering::Relaxed) >= audio_target;
            // [FIX] File audio murni (has_video = false) gak akan PERNAH
            // ngisi video_q (video_decode_loop keluar cepat begitu gak
            // nemu stream video) -- tanpa `!self.has_video ||` di sini,
            // video_ready gak akan pernah true buat file kayak gitu, dan
            // wait_for_seek_ready() bakal SELALU kena timeout 400ms penuh
            // tiap kali play()/seek() dipanggil, walau audionya udah siap
            // dari awal.
            let video_ready = !self.has_video || {
                let q = self.shared.video_q.lock().unwrap();
                q.back().map(|f| f.pts + 0.05 >= target).unwrap_or(false)
            };
            if audio_ready && video_ready {
                return;
            }
            thread::sleep(Duration::from_millis(5));
        }
        // Timeout -- lanjut aja apa adanya. Mending mulai agak nunda drpd
        // UI (tombol Play/seekbar) kekunci nunggu tanpa batas.
    }
}

impl Drop for PlayerEngine {
    fn drop(&mut self) {
        self.close();
    }
}

/// Loop thread VIDEO: demux+decode video dari file handle-nya SENDIRI,
/// isi video_q. Sama sekali gak nyentuh apapun soal audio -- itu urusan
/// audio_decode_loop() yang jalan di thread lain, file handle lain.
/// Jalan independen dari GIL Python — cuma method get_frame() yang perlu GIL,
/// dan itu cuma buat konversi Vec<u8> -> PyArray, bukan buat decode-nya.
fn video_decode_loop(file_path: String, shared: Arc<Shared>) {
    let path = Path::new(&file_path);
    let mut input_ctx = match ffmpeg_next::format::input(&path) {
        Ok(i) => i,
        Err(e) => {
            eprintln!("[media_engine] video thread gagal buka file: {e}");
            return;
        }
    };

    let video_idx = match input_ctx.streams().best(ffmpeg_next::media::Type::Video) {
        Some(s) => s.index(),
        None => return,
    };
    let mut vdecoder = {
        let stream = input_ctx.streams().best(ffmpeg_next::media::Type::Video).unwrap();
        match ffmpeg_next::codec::context::Context::from_parameters(stream.parameters())
            .ok()
            .and_then(|ctx| ctx.decoder().video().ok())
        {
            Some(d) => d,
            None => return,
        }
    };
    let vwidth = vdecoder.width();
    let vheight = vdecoder.height();
    let vtb = {
        let s = input_ctx.streams().best(ffmpeg_next::media::Type::Video).unwrap();
        let tb = s.time_base();
        if tb.denominator() > 0 { tb.numerator() as f64 / tb.denominator() as f64 } else { 0.0 }
    };

    let mut scaler: Option<ffmpeg_next::software::scaling::Context> = None;
    let mut vframe = ffmpeg_next::frame::Video::empty();
    let mut applied_seek_seq: u64 = 0;
    let mut sent_eof = false;

    // SATU iterator paket, dipakai berulang -- BUKAN dibikin baru tiap
    // baca satu paket (`input_ctx.packets().next()` tiap iterasi loop).
    // Pola lama itu warisan dari kode awal yang cuma dites buat pemakaian
    // pendek/bounded (seek_frame/read_next_frame, paling banyak ratusan
    // panggilan). Di sini dipanggil di loop tanpa henti selama BERMENIT-
    // MENIT, bisa ratusan ribu kali -- kemungkinan besar itu yang bikin
    // audio thread berhenti baca prematur (bug/limitasi internal iterator
    // yang gak pernah ketauan di skala pemakaian sebelumnya).
    // `Option` di sini biar gampang "dilepas" (di-None-in) pas mau seek --
    // seek() butuh &mut input_ctx eksklusif, gak bisa dipinjem bareng
    // sama iterator yang masih hidup.
    // [FIX] `#[allow(unused_assignments)]` -- rustc nganggep `packet_iter =
    // None;` di bawah "gak pernah dibaca" karena langsung ditimpa lagi sama
    // `Some(...)`, padahal assignment ke None itu SENGAJA: itu yang bikin
    // borrow ke `input_ctx` dari iterator lama dilepas sebelum `seek()`
    // dipanggil. Efek sampingnya (drop borrow) penting, bukan nilainya --
    // jadi warning-nya false-positive, cukup di-silence, gak perlu direstruktur.
    #[allow(unused_assignments)]
    let mut packet_iter = Some(input_ctx.packets());

    loop {
        if shared.stop.load(Ordering::Relaxed) {
            break;
        }

        // Generation counter: bandingin sama versi terakhir yang UDAH
        // diterapin thread ini. Kalau beda, ada seek baru (manual ATAU
        // auto-loop-restart) yang belom diterapin -- terapin sekarang.
        let current_seq = shared.seek_seq.load(Ordering::SeqCst);
        if current_seq != applied_seek_seq {
            packet_iter = None; // lepas borrow dulu biar input_ctx bisa dipinjem buat seek()
            let sec = *shared.seek_target.lock().unwrap();
            let ts = av_time_base_ts(sec);
            if input_ctx.seek(ts, ..ts).is_ok() {
                vdecoder.flush();
                shared.video_q.lock().unwrap().clear();
                shared.reset_clock(sec);
                shared.eof.store(false, Ordering::Relaxed);
                sent_eof = false;
            }
            packet_iter = Some(input_ctx.packets()); // iterator baru, mulai dari posisi abis seek
            applied_seek_seq = current_seq;
        }

        if !shared.playing.load(Ordering::Relaxed) {
            if shared.step_request.swap(false, Ordering::SeqCst) {
                // Frame-step: paksa decode satu frame video ke depan meski
                // lagi paused, lalu geser clock persis ke pts frame itu --
                // jadi get_frame() normal di sisi Python otomatis nemu &
                // nampilin frame ini di tick berikutnya, gak perlu jalur
                // spesial di get_frame(). Blok ini bounded (maks 500x) dan
                // jarang dipanggil, jadi tetep pakai iterator yang sama.
                let mut produced = false;
                for _ in 0..500 {
                    let next_packet = packet_iter.as_mut().and_then(|it| it.next());
                    let (stream, packet) = match next_packet {
                        Some(p) => p,
                        None => {
                            shared.eof.store(true, Ordering::Relaxed);
                            break;
                        }
                    };
                    if stream.index() != video_idx {
                        continue;
                    }
                    if vdecoder.send_packet(&packet).is_ok() && vdecoder.receive_frame(&mut vframe).is_ok() {
                        let pts = vframe.timestamp().unwrap_or(0) as f64 * vtb;
                        if let Ok(rgb) = scale_to_rgb(&vframe, &mut scaler, vdecoder.format(), vwidth, vheight) {
                            shared.video_q.lock().unwrap().push_back(QueuedFrame { rgb, pts });
                            shared.reset_clock(pts);
                            produced = true;
                        }
                    }
                    if produced { break; }
                }
            } else {
                thread::sleep(Duration::from_millis(10));
            }
            continue;
        }

        // Backpressure: jangan decode lebih cepet dari yang dibutuhin buat
        // nampilin. Cuma soal video_q di sini -- gak ada lagi urusan audio
        // yang ikut nge-gate video kayak dulu.
        let q_len = shared.video_q.lock().unwrap().len();
        if q_len >= MAX_VIDEO_FRAMES {
            thread::sleep(Duration::from_millis(5));
            continue;
        }

        let next_packet = packet_iter.as_mut().and_then(|it| it.next());
        let (stream, packet) = match next_packet {
            Some(p) => p,
            None => {
                if !sent_eof {
                    let _ = vdecoder.send_eof();
                    sent_eof = true;
                    // [FIX] Sama kayak audio_decode_loop: abis send_eof(),
                    // decoder masuk mode draining -- WAJIB terus manggil
                    // receive_frame() buat ngeluarin sisa frame yg masih
                    // ke-buffer internal (B-frame reorder/decode delay).
                    // Sebelumnya ini gak dipanggil -> beberapa frame
                    // terakhir video ilang juga (gak seketara audio krn gak
                    // ada log-nya, tapi bug-nya sama persis).
                    while vdecoder.receive_frame(&mut vframe).is_ok() {
                        let pts = vframe.timestamp().unwrap_or(0) as f64 * vtb;
                        if let Ok(rgb) = scale_to_rgb(&vframe, &mut scaler, vdecoder.format(), vwidth, vheight) {
                            shared.video_q.lock().unwrap().push_back(QueuedFrame { rgb, pts });
                        }
                    }
                    eprintln!(
                        "[media_engine] video thread nyampe EOF file fisik (udah di-drain) @ posisi ~{:.2}s",
                        shared.position(),
                    );
                }
                if shared.loop_enabled.load(Ordering::Relaxed) {
                    // Auto-restart: minta seek ke detik 0 lewat generation
                    // counter yang sama kayak seek manual -- audio_decode_loop
                    // bakal ikut nangkep & seek balik ke 0 juga di iterasi
                    // dia berikutnya, independen, gak perlu ditunggu di sini.
                    *shared.seek_target.lock().unwrap() = 0.0;
                    shared.seek_seq.fetch_add(1, Ordering::SeqCst);
                } else {
                    shared.eof.store(true, Ordering::Relaxed);
                }
                thread::sleep(Duration::from_millis(20));
                continue;
            }
        };

        if stream.index() != video_idx {
            continue;
        }

        if vdecoder.send_packet(&packet).is_ok() {
            while vdecoder.receive_frame(&mut vframe).is_ok() {
                let pts = vframe.timestamp().unwrap_or(0) as f64 * vtb;
                if let Ok(rgb) = scale_to_rgb(&vframe, &mut scaler, vdecoder.format(), vwidth, vheight) {
                    shared.video_q.lock().unwrap().push_back(QueuedFrame { rgb, pts });
                }
            }
        }
    }
}

/// Loop thread AUDIO: demux+decode audio dari file handle-nya SENDIRI,
/// resample ke format device, dorong ke ring buffer. Sama sekali gak
/// nyentuh video_q -- itu urusan video_decode_loop(). Backpressure &
/// seek-nya independen total dari video, jadi video yang lagi berat gak
/// akan pernah bisa bikin thread ini (dan ring buffer-nya) ke-block.
///
/// Helper: resample SATU frame audio hasil decode -> push ke ring buffer.
/// Dipisah dari loop utama (BUKAN cuma dipanggil sekali) karena dipanggil
/// dari DUA tempat: (1) jalur normal abis receive_frame() dalem loop paket,
/// (2) jalur drain abis send_eof() -- FFmpeg codec kayak AAC/Opus sering
/// nahan beberapa frame di buffer internal (decode delay/reorder), dan itu
/// CUMA keluar via receive_frame() lagi SETELAH send_eof() dipanggil.
/// Sebelumnya jalur (2) ini gak ada sama sekali -> sample-sample terakhir
/// yang masih ke-buffer di decoder ilang gitu aja, bikin audio berhenti
/// sebelum video abis walau track audio-nya sebenernya sama panjang.
fn push_resampled_audio_frame(
    aframe: &ffmpeg_next::frame::Audio,
    resampler: &mut Option<ffmpeg_next::software::resampling::Context>,
    producer: &mut AudioProducer,
    shared: &Shared,
    decoder_channels: i32,
    out_layout: ffmpeg_next::util::channel_layout::ChannelLayout,
    out_rate: u32,
    out_channels: u16,
    expected_audio_pts: &mut f64,
    atb: f64,
) {
    // Ambil PTS frame aktual, atau gunakan expected jika tidak ada
    let frame_pts = aframe.timestamp().map(|ts| ts as f64 * atb).unwrap_or(*expected_audio_pts);

    // 1. PAD SILENCE JIKA ADA GAP (Start Delay / Audio Bolong)
    // Toleransi 0.1 detik untuk mencegah pergeseran sync.
    if frame_pts > *expected_audio_pts + 0.1 {
        let raw_gap_sec = frame_pts - *expected_audio_pts;

        // [FIX] BATASI gap yang di-pad. Gap gede (misal belasan detik)
        // hampir pasti BUKAN silence asli di track, tapi anomali PTS
        // (glitch timestamp/reorder codec di titik tertentu file).
        // Kalau dibiarin tanpa batas, loop backpressure di bawah bakal
        // ngabisin waktu WALL-CLOCK nyata cuma buat nyorong silence
        // sebanyak itu ke ring buffer -- sementara video jalan terus
        // independen dan bisa nyampe EOF duluan (nge-trigger shared.stop)
        // SEBELUM decode thread ini sempet balik ngedecode sisa audio
        // ASLI setelah titik gap tsb. Efeknya: sisa audio asli abis
        // titik gap ini ilang total, kedengeran kayak "audio berhenti
        // duluan" walau file aslinya audio-nya lebih panjang.
        // Dicap ke MAX_GAP_PAD_SEC detik: gap wajar (start delay dsb)
        // tetep di-pad buat sync, gap ekstrem cuma di-log & di-resync
        // tanpa nelen waktu real audio berikutnya.
        const MAX_GAP_PAD_SEC: f64 = 2.0;
        if raw_gap_sec > MAX_GAP_PAD_SEC {
            eprintln!(
                "[media_engine] PTS jump gede ({:.2}s) kedetect @ ~{:.2}s -- dianggap glitch timestamp (bukan silence asli), pad dibatasin ke {:.1}s biar sisa audio asli abis titik ini tetep sempet ke-decode",
                raw_gap_sec, shared.position(), MAX_GAP_PAD_SEC,
            );
        }
        let gap_sec = raw_gap_sec.min(MAX_GAP_PAD_SEC);
        let gap_samples = (gap_sec * out_rate as f64) as usize * out_channels as usize;
        let silence = vec![0.0f32; 2048.min(gap_samples)];
        let mut pushed_total = 0;
        let a_cap = (out_rate as usize) * (out_channels as usize) * 2;

        while pushed_total < gap_samples {
            if shared.stop.load(Ordering::Relaxed) || shared.audio_flush.load(Ordering::Relaxed) {
                break;
            }
            if producer.occupied_len() >= a_cap {
                thread::sleep(Duration::from_millis(5));
                continue;
            }
            let to_push = (gap_samples - pushed_total).min(silence.len());
            let pushed = producer.push_slice(&silence[..to_push]);
            pushed_total += pushed;
            shared.audio_buffered_hint.store(producer.occupied_len(), Ordering::Relaxed);
        }
    }

    // 2. SETUP RESAMPLER
    if resampler.is_none() {
        let src_layout = if aframe.channel_layout().bits() != 0 {
            aframe.channel_layout()
        } else {
            ffmpeg_next::util::channel_layout::ChannelLayout::default(decoder_channels)
        };
        *resampler = match ffmpeg_next::software::resampling::Context::get(
            aframe.format(), src_layout, aframe.rate(),
            ffmpeg_next::util::format::Sample::F32(ffmpeg_next::util::format::sample::Type::Packed),
            out_layout, out_rate,
        ) {
            Ok(r) => Some(r),
            Err(e) => {
                eprintln!("[media_engine] gagal bikin audio resampler: {e}");
                None
            }
        };
    }

    // 3. RESAMPLE & PUSH FRAME AKTUAL (Anti-Drop Backpressure)
    if let Some(rs) = resampler.as_mut() {
        let mut resampled = ffmpeg_next::frame::Audio::empty();
        match rs.run(aframe, &mut resampled) {
            Ok(_) => {
                let n_samples = resampled.samples() * out_channels as usize;
                let raw = resampled.data(0);
                if raw.len() >= n_samples * 4 {
                    let floats: &[f32] = unsafe {
                        std::slice::from_raw_parts(raw.as_ptr() as *const f32, n_samples)
                    };

                    // [BARU] Downmix ke mono & simpen ke viz_ring buat FFT
                    // visualizer. Ini SELALU jalan (gak peduli backpressure
                    // ring buffer playback di bawah) karena tujuannya cuma
                    // nampilin "apa yang lagi didecode sekarang", bukan
                    // ikut aturan sinkronisasi audio-video.
                    {
                        let ch = out_channels as usize;
                        let mut viz = shared.viz_ring.lock().unwrap();
                        for frame in floats.chunks(ch) {
                            let mono = frame.iter().sum::<f32>() / ch as f32;
                            viz.push_back(mono);
                        }
                        while viz.len() > VIZ_RING_CAP {
                            viz.pop_front();
                        }
                    }

                    let mut pushed_total = 0;
                    let a_cap = (out_rate as usize) * (out_channels as usize) * 2;

                    // Loop ini menjamin tidak ada 1 sampel pun yang dibuang saat ring buffer penuh
                    while pushed_total < n_samples {
                        if shared.stop.load(Ordering::Relaxed) || shared.audio_flush.load(Ordering::Relaxed) {
                            break;
                        }
                        if producer.occupied_len() >= a_cap {
                            thread::sleep(Duration::from_millis(5));
                            continue;
                        }
                        let chunk = &floats[pushed_total..];
                        let pushed = producer.push_slice(chunk);
                        pushed_total += pushed;
                        shared.audio_buffered_hint.store(producer.occupied_len(), Ordering::Relaxed);
                    }
                }
            }
            Err(e) => {
                eprintln!("[media_engine] resample audio gagal @ ~{:.2}s: {e}", shared.position());
            }
        }
    }

    // 4. UPDATE EXPECTED PTS UNTUK ITERASI BERIKUTNYA
    let duration_sec = aframe.samples() as f64 / aframe.rate() as f64;
    *expected_audio_pts = frame_pts + duration_sec;
}

fn audio_decode_loop(file_path: String, shared: Arc<Shared>, mut producer: AudioProducer) {
    let path = Path::new(&file_path);
    let mut input_ctx = match ffmpeg_next::format::input(&path) {
        Ok(i) => i,
        Err(e) => {
            eprintln!("[media_engine] audio thread gagal buka file: {e}");
            return;
        }
    };

    let audio_idx = match input_ctx.streams().best(ffmpeg_next::media::Type::Audio) {
        Some(s) => s.index(),
        None => return,
    };

    // Time base stream audio -- dipakai buat konversi PTS mentah (dalam unit
    // stream) ke detik, biar bisa dibandingin sama expected_audio_pts.
    let atb = {
        let s = input_ctx.streams().best(ffmpeg_next::media::Type::Audio).unwrap();
        let tb = s.time_base();
        if tb.denominator() > 0 { tb.numerator() as f64 / tb.denominator() as f64 } else { 0.0 }
    };

    let mut adecoder = {
        let stream = input_ctx.streams().best(ffmpeg_next::media::Type::Audio).unwrap();
        match ffmpeg_next::codec::context::Context::from_parameters(stream.parameters())
            .ok()
            .and_then(|ctx| ctx.decoder().audio().ok())
        {
            Some(d) => d,
            None => return,
        }
    };

    let out_rate = shared.out_sample_rate.load(Ordering::Relaxed) as u32;
    let out_channels = shared.out_channels.load(Ordering::Relaxed) as u16;
    let out_layout = ffmpeg_next::util::channel_layout::ChannelLayout::default(out_channels as i32);
    let a_cap = (out_rate as usize) * (out_channels as usize) * 2; // ~2 detik, sama kayak sebelumnya

    // State tracker: PTS (dalam detik) yang "seharusnya" terjadi berikutnya
    // di ring buffer, dipakai buat deteksi gap (start delay / bolong di
    // tengah) dan nyuntik silence biar timeline audio gak geser ke kiri.
    let mut expected_audio_pts: f64 = 0.0;

    let mut resampler: Option<ffmpeg_next::software::resampling::Context> = None;
    let mut aframe = ffmpeg_next::frame::Audio::empty();
    let mut applied_seek_seq: u64 = 0;
    let mut sent_eof = false;

    // Sama kayak video_decode_loop: SATU iterator, dipakai berulang, cuma
    // dibikin ulang pas ada seek. Lihat comment lebih lengkap di
    // video_decode_loop soal kenapa ini penting.
    // [FIX] Sama kayak di video_decode_loop -- assignment ke None di bawah
    // sengaja buat lepas borrow sebelum seek(), bukan gak kepake.
    #[allow(unused_assignments)]
    let mut packet_iter = Some(input_ctx.packets());

    loop {
        if shared.stop.load(Ordering::Relaxed) {
            break;
        }

        let current_seq = shared.seek_seq.load(Ordering::SeqCst);
        if current_seq != applied_seek_seq {
            packet_iter = None; // lepas borrow dulu biar input_ctx bisa dipinjem buat seek()
            let sec = *shared.seek_target.lock().unwrap();
            let ts = av_time_base_ts(sec);
            if input_ctx.seek(ts, ..ts).is_ok() {
                adecoder.flush();
                // reset_clock() aman dipanggil dari kedua thread (video
                // JUGA manggil ini buat generation yg sama) -- idempotent,
                // nulis base+flush yang sama, gak ada efek dobel.
                shared.reset_clock(sec);
                sent_eof = false;
            }
            packet_iter = Some(input_ctx.packets());
            applied_seek_seq = current_seq;

            // Abis seek, expected PTS harus di-reset ke target seek --
            // kalau enggak, frame pertama setelah seek bakal keliatan
            // "gap" palsu dibanding posisi lama.
            expected_audio_pts = sec;
        }

        if !shared.playing.load(Ordering::Relaxed) {
            thread::sleep(Duration::from_millis(10));
            continue;
        }

        if producer.occupied_len() >= a_cap {
            thread::sleep(Duration::from_millis(5));
            continue;
        }

        let next_packet = packet_iter.as_mut().and_then(|it| it.next());
        let (stream, packet) = match next_packet {
            Some(p) => p,
            None => {
                if !sent_eof {
                    let _ = adecoder.send_eof();
                    sent_eof = true;
                    // [FIX] send_eof() naruh decoder ke mode "draining" --
                    // WAJIB terus manggil receive_frame() sampe dia gak
                    // ngasih frame lagi, buat ngeluarin sisa frame yg masih
                    // ke-buffer internal (decode delay/reorder, umum di
                    // AAC/Opus dll). Sebelumnya ini gak dipanggil sama
                    // sekali abis send_eof() -- makanya audio berhenti
                    // KEDENGERAN lebih awal drpd posisi EOF fisik yang
                    // dilog di bawah (buffer di ring buffer, yg diisi dari
                    // sample2 sebelum EOF, keburu abis sebelum sample2 sisa
                    // hasil drain ini nyampe -- padahal seharusnya ada).
                    while adecoder.receive_frame(&mut aframe).is_ok() {
                        push_resampled_audio_frame(
                            &aframe, &mut resampler, &mut producer, &shared,
                            adecoder.channels() as i32, out_layout, out_rate, out_channels,
                            &mut expected_audio_pts, atb,
                        );
                    }
                    eprintln!(
                        "[media_engine] audio thread nyampe EOF file fisik (udah di-drain) @ posisi ~{:.2}s (kalau ini muncul jauh sebelum durasi video abis, kemungkinan track audio di file emang lebih pendek drpd video, bukan bug decode)",
                        shared.position(),
                    );
                }
                // EOF di sisi audio gak nge-trigger apa2 (bukan yg megang
                // status "selesai" buat UI, itu video_decode_loop). Kalau
                // loop_enabled, video yang bakal bump seek_seq -- thread
                // ini otomatis ikut nangkep lewat cek generation di atas.
                thread::sleep(Duration::from_millis(20));
                continue;
            }
        };

        if stream.index() != audio_idx {
            continue;
        }

        if let Err(e) = adecoder.send_packet(&packet) {
            eprintln!("[media_engine] audio send_packet gagal @ ~{:.2}s: {e}", shared.position());
            continue;
        }
        while adecoder.receive_frame(&mut aframe).is_ok() {
            push_resampled_audio_frame(
                &aframe, &mut resampler, &mut producer, &shared,
                adecoder.channels() as i32, out_layout, out_rate, out_channels,
                &mut expected_audio_pts, atb,
            );
        }
    }
}


fn scale_to_rgb(
    decoded: &ffmpeg_next::frame::Video,
    scaler_slot: &mut Option<ffmpeg_next::software::scaling::Context>,
    src_format: ffmpeg_next::util::format::Pixel,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, ffmpeg_next::Error> {
    let scaler = match scaler_slot {
        Some(s) => s,
        None => {
            let ctx = ffmpeg_next::software::scaling::Context::get(
                src_format, width, height,
                ffmpeg_next::util::format::Pixel::RGB24, width, height,
                ffmpeg_next::software::scaling::flag::Flags::BILINEAR,
            )?;
            scaler_slot.insert(ctx)
        }
    };

    let mut rgb_frame = ffmpeg_next::frame::Video::new(
        ffmpeg_next::util::format::Pixel::RGB24, width, height,
    );
    scaler.run(decoded, &mut rgb_frame)?;

    let stride = rgb_frame.stride(0);
    let row_width = (width as usize) * 3;
    let mut data = Vec::with_capacity((height as usize) * row_width);
    let raw_data = rgb_frame.data(0);
    for y in 0..(height as usize) {
        let start = y * stride;
        data.extend_from_slice(&raw_data[start..start + row_width]);
    }
    Ok(data)
}

// ═══════════════════════════════════════════════
// BAGIAN 4: ANALISA AUDIO -- envelope waveform + BPM detection.
// Dipakai buat gambar preview waveform (kayak di audio cutter) dan
// estimasi tempo lagu. Beda dari PlayerEngine (bagian 3): ini decode
// SELURUH file sekaligus di luar playback, bukan streaming real-time.
// ═══════════════════════════════════════════════

/// Decode seluruh track audio terbaik di file jadi mono f32 pada
/// `out_rate` tertentu. Dipakai bareng buat envelope waveform & BPM
/// detection -- keduanya butuh representasi sample yang sama, jadi
/// decode-nya cukup sekali.
///
/// Sengaja di-downsample (bukan pakai sample rate asli file) karena buat
/// dua analisa ini kita gak butuh presisi sample-per-sample -- 22050Hz udah
/// lebih dari cukup buat nangkep amplop energi (envelope) & onset drum/kick
/// (BPM), sambil ngirit memori & waktu decode buat file yang panjang.
fn decode_audio_mono(file_path: &str, out_rate: u32) -> PyResult<Vec<f32>> {
    init_ffmpeg()?;
    let path = Path::new(file_path);
    let mut ictx = ffmpeg_next::format::input(&path)
        .map_err(|e| PyIOError::new_err(format!("Buka file: {}", e)))?;

    let audio_idx = ictx.streams()
        .best(ffmpeg_next::media::Type::Audio)
        .ok_or_else(|| PyValueError::new_err("Tidak ada aliran audio"))?
        .index();

    let params = ictx.stream(audio_idx).unwrap().parameters();
    let ctx = ffmpeg_next::codec::context::Context::from_parameters(params)
        .map_err(|e| PyRuntimeError::new_err(format!("Konteks dekoder audio: {}", e)))?;
    let mut decoder = ctx.decoder().audio()
        .map_err(|e| PyRuntimeError::new_err(format!("Buat dekoder audio: {}", e)))?;

    let out_layout = ffmpeg_next::util::channel_layout::ChannelLayout::MONO;
    let mut resampler: Option<ffmpeg_next::software::resampling::Context> = None;

    let mut samples: Vec<f32> = Vec::new();
    let mut decoded = ffmpeg_next::frame::Audio::empty();

    // Helper lokal: resample 1 frame yang udah didecode & append hasilnya
    // ke `samples`. Resampler dibangun lazy (baru pas frame pertama)
    // karena butuh tau format/channel-layout/rate SUMBER dulu -- sama
    // persis alasannya kayak di push_resampled_audio_frame() (bagian 3),
    // format decoder kadang beda dari yang dilaporin stream parameters.
    macro_rules! resample_and_push {
        ($frame:expr) => {{
            if resampler.is_none() {
                let src_layout = if $frame.channel_layout().bits() != 0 {
                    $frame.channel_layout()
                } else {
                    ffmpeg_next::util::channel_layout::ChannelLayout::default(decoder.channels() as i32)
                };
                resampler = ffmpeg_next::software::resampling::Context::get(
                    $frame.format(), src_layout, $frame.rate(),
                    ffmpeg_next::util::format::Sample::F32(ffmpeg_next::util::format::sample::Type::Packed),
                    out_layout, out_rate,
                ).ok();
            }
            if let Some(rs) = resampler.as_mut() {
                let mut resampled = ffmpeg_next::frame::Audio::empty();
                if rs.run($frame, &mut resampled).is_ok() {
                    let n = resampled.samples();
                    let raw = resampled.data(0);
                    if raw.len() >= n * 4 {
                        let floats: &[f32] = unsafe {
                            std::slice::from_raw_parts(raw.as_ptr() as *const f32, n)
                        };
                        samples.extend_from_slice(floats);
                    }
                }
            }
        }};
    }

    for (stream, packet) in ictx.packets() {
        if stream.index() != audio_idx { continue; }
        if decoder.send_packet(&packet).is_err() { continue; }
        while decoder.receive_frame(&mut decoded).is_ok() {
            resample_and_push!(&decoded);
        }
    }
    // Drain sisa frame yang masih ke-buffer internal decoder (decode
    // delay/reorder) -- tanpa ini, ekor file (terutama AAC/Opus) bisa
    // ilang dari hasil analisa, sama kayak catatan di audio_decode_loop().
    let _ = decoder.send_eof();
    while decoder.receive_frame(&mut decoded).is_ok() {
        resample_and_push!(&decoded);
    }

    Ok(samples)
}

/// Envelope waveform: ringkas `samples` jadi `target_points` nilai RMS
/// (0..1 setelah dinormalisasi), buat digambar sebagai preview waveform di
/// UI (mis. audio cutter / tag editor). Dipecah per-chunk & dihitung
/// paralel lewat rayon karena tiap chunk independen -- gak ada
/// ketergantungan antar-chunk sama sekali.
fn compute_envelope(samples: &[f32], target_points: usize) -> Vec<f32> {
    let target_points = target_points.max(1);
    if samples.is_empty() {
        return vec![0.0; target_points];
    }
    let chunk_size = (samples.len() / target_points).max(1);

    let mut envelope: Vec<f32> = (0..target_points).into_par_iter().map(|i| {
        let start = i * chunk_size;
        if start >= samples.len() {
            return 0.0;
        }
        let end = (start + chunk_size).min(samples.len());
        let chunk = &samples[start..end];
        // RMS, bukan peak -- peak kelewat sensitif ke 1 sample transient
        // dan bikin waveform preview keliatan "berduri", RMS lebih halus
        // dan lebih ngegambarin persepsi kenyaringan.
        let sum_sq: f32 = chunk.iter().map(|s| s * s).sum();
        (sum_sq / chunk.len() as f32).sqrt()
    }).collect();

    let peak = envelope.iter().cloned().fold(0.0f32, f32::max);
    if peak > 0.0 {
        envelope.par_iter_mut().for_each(|v| *v /= peak);
    }
    envelope
}

/// Estimasi BPM lewat onset-energy + autocorrelation. Algoritma sengaja
/// dibikin ringan (bukan full spectral-flux multi-band) supaya cepet buat
/// file panjang:
/// 1. Energi RMS tiap window kecil (`hop` sample) -> "amplop energi" kasar.
/// 2. Onset strength = kenaikan energi positif antar-window (nangkep hit
///    kick/snare drum, transient lain diabaikan kalau energinya turun).
/// 3. Autocorrelation onset signal di rentang lag yang sesuai 60-200 BPM,
///    lag dengan korelasi tertinggi = periode antar-beat yang dominan.
/// Cukup akurat buat musik dengan beat yang jelas (pop/EDM/rock), kurang
/// reliable buat musik tanpa beat tetap (ambient, klasik rubato, dll) --
/// itu batasan algoritma ini, bukan bug.
fn detect_bpm(samples: &[f32], sample_rate: u32) -> f32 {
    const HOP: usize = 512;
    if samples.len() < HOP * 8 {
        return 0.0; // kependekan buat dianalisa
    }

    let n_frames = samples.len() / HOP;
    let energy: Vec<f32> = (0..n_frames).into_par_iter().map(|i| {
        let start = i * HOP;
        let end = (start + HOP).min(samples.len());
        let chunk = &samples[start..end];
        (chunk.iter().map(|s| s * s).sum::<f32>() / chunk.len() as f32).sqrt()
    }).collect();

    let onset: Vec<f32> = energy.windows(2).map(|w| (w[1] - w[0]).max(0.0)).collect();
    if onset.is_empty() {
        return 0.0;
    }

    let frame_rate = sample_rate as f32 / HOP as f32; // frame onset per detik
    const MIN_BPM: f32 = 60.0;
    const MAX_BPM: f32 = 200.0;
    let min_lag = ((60.0 / MAX_BPM) * frame_rate).round().max(1.0) as usize;
    let max_lag = (((60.0 / MIN_BPM) * frame_rate).round() as usize).min(onset.len().saturating_sub(1));

    if max_lag <= min_lag {
        return 0.0;
    }

    // Cari lag (dalam satuan frame onset) dengan autocorrelation
    // tertinggi -- itu periode antar-beat yang paling dominan. Kandidat
    // lag dicoba paralel karena tiap lag itung dot-product independen.
    let (best_lag, _) = (min_lag..=max_lag).into_par_iter().map(|lag| {
        let mut corr = 0.0f32;
        for i in 0..(onset.len() - lag) {
            corr += onset[i] * onset[i + lag];
        }
        (lag, corr)
    }).reduce(|| (min_lag, f32::MIN), |a, b| if b.1 > a.1 { b } else { a });

    if best_lag == 0 {
        return 0.0;
    }
    60.0 * frame_rate / best_lag as f32
}

/// [BARU] Analisa audio lengkap buat 1 file: envelope waveform (buat
/// preview di UI, mis. audio cutter/tag editor) + estimasi BPM, dalam satu
/// kali decode (biar gak decode file yang sama dua kali).
///
/// `target_points`: jumlah titik envelope yang mau digambar (mis. 800 buat
/// waveform selebar 800px di layar).
///
/// Balikin (array_envelope_0..1, bpm). bpm = 0.0 kalau gagal dideteksi
/// (file kependekan / gak ada beat yang jelas).
#[pyfunction]
fn analyze_waveform(py: Python<'_>, file_path: &str, target_points: usize) -> PyResult<(Py<PyArray1<f32>>, f32)> {
    const ANALYSIS_RATE: u32 = 22050;
    let samples = decode_audio_mono(file_path, ANALYSIS_RATE)?;
    if samples.is_empty() {
        return Err(PyValueError::new_err("Tidak ada sample audio yang bisa dibaca dari file ini"));
    }

    let envelope = compute_envelope(&samples, target_points);
    let bpm = detect_bpm(&samples, ANALYSIS_RATE);

    let arr = Array1::from_vec(envelope);
    Ok((arr.into_pyarray(py).into(), bpm))
}

/// [BARU] Expose `decode_audio_mono` langsung ke Python -- gantiin
/// subprocess `ffmpeg -f s16le pipe:1` yang sebelumnya dipakai AudioLoader
/// di macan_visualizer.py buat decode seluruh track ke PCM sebelum di-FFT.
/// Balikin array float32 mono ternormalisasi [-1.0..1.0], sudah di-resample
/// ke `out_rate`. Satu proses (gak spawn subprocess baru), jadi gak perlu
/// lagi cari-cari path ffmpeg statis/bundled/PATH sistem di sisi Python.
#[pyfunction]
fn decode_audio(py: Python<'_>, file_path: &str, out_rate: u32) -> PyResult<Py<PyArray1<f32>>> {
    let samples = decode_audio_mono(file_path, out_rate)?;
    let arr = Array1::from_vec(samples);
    Ok(arr.into_pyarray(py).into())
}

/// [BARU] Versi array publik dari compute_envelope() (dipakai internal oleh
/// analyze_waveform()) -- bedanya, fungsi ini kerja di atas array sample
/// yang SUDAH ADA di tangan Python (mis. hasil decode_audio() sekali di
/// awal), BUKAN decode dari file path lagi. Gantiin
/// `media_tools.compute_waveform_envelope()` (crate lama) yang dipakai
/// WaveformWidget di audio_cutter.py -- widget itu nge-decode file SEKALI
/// lalu simpen array-nya di memori buat digambar ulang tiap kali user
/// zoom/scroll (gak decode ulang dari file tiap kali).
///
/// Beda penting dengan analyze_waveform() (yang balikin RMS ternormalisasi
/// 0..1 buat 1x render awal): fungsi ini balikin min/max MENTAH per kolom
/// (bukan ternormalisasi) supaya rendering waveform yang di-zoom tetap
/// nangkep transient tajam, bukan cuma "amplop" RMS yang halus.
///
/// Balikin (mins, maxs, rmss, firsts) -- KEEMPATNYA array paralel sepanjang
/// `target_points`. `firsts[i]` = sample PERTAMA di chunk ke-i (dipakai
/// caller Python sebagai representasi "downsampled waveform" buat digambar
/// sebagai garis/area, terpisah dari mins/maxs/rmss yang dipakai buat
/// styling lain) -- BUKAN sample pertama dari keseluruhan array (itu beda
/// makna, jangan disamakan pas nge-debug pemakaiannya).
#[pyfunction]
fn compute_waveform_envelope(
    py: Python<'_>,
    samples: numpy::PyReadonlyArray1<f32>,
    target_points: usize,
) -> PyResult<(Py<PyArray1<f32>>, Py<PyArray1<f32>>, Py<PyArray1<f32>>, Py<PyArray1<f32>>)> {
    let samples = samples.as_slice()
        .map_err(|_| PyValueError::new_err("Array sample harus contiguous (C-order)"))?;
    let target_points = target_points.max(1);

    if samples.is_empty() {
        let zeros = || Array1::from_vec(vec![0.0f32; target_points]).into_pyarray(py).into();
        return Ok((zeros(), zeros(), zeros(), zeros()));
    }

    let chunk_size = (samples.len() / target_points).max(1);
    let chunks: Vec<(f32, f32, f32, f32)> = (0..target_points).into_par_iter().map(|i| {
        let start = i * chunk_size;
        if start >= samples.len() {
            return (0.0, 0.0, 0.0, 0.0);
        }
        let end = (start + chunk_size).min(samples.len());
        let seg = &samples[start..end];
        let mn = seg.iter().cloned().fold(f32::INFINITY, f32::min);
        let mx = seg.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
        let sum_sq: f32 = seg.iter().map(|s| s * s).sum();
        let rms = (sum_sq / seg.len() as f32).sqrt();
        (mn, mx, rms, seg[0])
    }).collect();

    let mins: Vec<f32> = chunks.iter().map(|c| c.0).collect();
    let maxs: Vec<f32> = chunks.iter().map(|c| c.1).collect();
    let rmss: Vec<f32> = chunks.iter().map(|c| c.2).collect();
    let firsts: Vec<f32> = chunks.iter().map(|c| c.3).collect();

    Ok((
        Array1::from_vec(mins).into_pyarray(py).into(),
        Array1::from_vec(maxs).into_pyarray(py).into(),
        Array1::from_vec(rmss).into_pyarray(py).into(),
        Array1::from_vec(firsts).into_pyarray(py).into(),
    ))
}

/// [BARU] Expose detect_bpm() (helper internal di atas, dipakai
/// analyze_waveform()) langsung ke Python buat kasus yang sample-nya udah
/// ada di tangan (mis. hasil decode_audio() sebelumnya) dan gak mau decode
/// file yang sama 2x cuma buat estimasi BPM. Gantiin
/// `media_tools.detect_bpm()` (crate lama). Kalau belum ada sample sama
/// sekali, lebih murah langsung pakai analyze_waveform() (decode + envelope
/// + BPM sekaligus dalam 1x baca file).
#[pyfunction]
#[pyo3(name = "detect_bpm")]
fn detect_bpm_py(samples: numpy::PyReadonlyArray1<f32>, sample_rate: u32) -> PyResult<f32> {
    let samples = samples.as_slice()
        .map_err(|_| PyValueError::new_err("Array sample harus contiguous (C-order)"))?;
    Ok(detect_bpm(samples, sample_rate))
}

/// [BARU] Analisa spektrum FFT untuk chunk sample sembarang -- dipakai
/// AudioVisualizer di macan_visualizer.py buat bar/wave visualizer + deteksi
/// bass level (BreathableArtwork). Gantiin crate `macan_fft` yang tadinya
/// berdiri sendiri, sekarang jadi bagian dari media_engine biar cuma satu
/// binary native yang perlu di-maintain/di-build.
///
/// API sengaja dibikin kompatibel 1:1 sama `macan_fft.MacanFft` lama:
/// constructor `SpectrumAnalyzer(fft_size)` (fft_size harus pangkat 2),
/// method `.compute(samples)` -> magnitude LINEAR (bukan dB, beda dengan
/// PlayerEngine.get_spectrum() yang memang didesain buat tampilan dB),
/// panjang fft_size//2+1, window Hanning sudah diterapkan di dalam
/// compute() jadi caller Python TIDAK perlu windowing manual lagi.
#[pyclass]
struct SpectrumAnalyzer {
    fft_size: usize,
    window: Vec<f32>,
    fft: Arc<dyn Fft<f32>>,
}

#[pymethods]
impl SpectrumAnalyzer {
    #[new]
    fn new(fft_size: usize) -> PyResult<Self> {
        if fft_size == 0 || (fft_size & (fft_size - 1)) != 0 {
            return Err(PyValueError::new_err("fft_size harus pangkat 2 (mis. 512, 1024, 2048)"));
        }
        // Precompute window Hanning & rencana FFT sekali di constructor --
        // sama seperti strategi macan_fft lama, biar gak dihitung ulang
        // tiap panggilan .compute() (dipanggil ~50x/detik di visualizer).
        let window: Vec<f32> = (0..fft_size).map(|i| {
            0.5 - 0.5 * (2.0 * std::f32::consts::PI * i as f32 / (fft_size - 1) as f32).cos()
        }).collect();
        let mut planner = FftPlanner::<f32>::new();
        let fft = planner.plan_fft_forward(fft_size);
        Ok(SpectrumAnalyzer { fft_size, window, fft })
    }

    fn compute(&self, py: Python<'_>, samples: Vec<f32>) -> PyResult<Py<PyArray1<f32>>> {
        if samples.len() != self.fft_size {
            return Err(PyValueError::new_err(format!(
                "Jumlah sample ({}) harus sama dengan fft_size ({})",
                samples.len(), self.fft_size
            )));
        }

        let mut buf: Vec<Complex32> = samples.iter().zip(self.window.iter())
            .map(|(&s, &w)| Complex32::new(s * w, 0.0))
            .collect();
        self.fft.process(&mut buf);

        // Sinyal input real -> spektrum Hermitian-symmetric, cuma
        // fft_size//2+1 bin pertama yang unik (sama seperti np.fft.rfft
        // dulu di macan_fft/fallback numpy).
        let half = self.fft_size / 2 + 1;
        let magnitude: Vec<f32> = buf[..half].iter().map(|c| c.norm()).collect();
        let arr = Array1::from_vec(magnitude);
        Ok(arr.into_pyarray(py).into())
    }
}

// ═══════════════════════════════════════════════
// BAGIAN 5: KONVERTER AUDIO/VIDEO -- transcode/remux native lewat
// ffmpeg-next, gantiin subprocess ffmpeg.exe (kayak yang dipakai Macan
// Converter sekarang) buat kasus umum. Mendukung 2 mode per track:
//   - codec = None  -> stream copy (remux, gak re-encode, CEPAT & lossless,
//     tapi output codec ngikut sumber -- gak bisa ganti container yg gak
//     kompatibel sama codec asalnya, mis. H.265 ke .avi)
//   - codec = Some("libx264"/"aac"/dll) -> full transcode
// ═══════════════════════════════════════════════

/// Cek apakah muxer output butuh "global header" (banyak container modern
/// kayak MP4/MOV/MKV butuh ini buat stream yang di-encode -- extradata
/// SPS/PPS dkk ditaro di container header, bukan di tiap paket). Encoder
/// WAJIB tau ini SEBELUM open(), makanya dicek duluan sebelum setup encoder.
fn needs_global_header(octx: &ffmpeg_next::format::context::Output) -> bool {
    octx.format().flags().contains(ffmpeg_next::format::Flags::GLOBAL_HEADER)
}

/// Konversi/transcode media (audio dan/atau video) ke file baru.
///
/// - `video_codec`/`audio_codec`: nama encoder ffmpeg (mis. "libx264",
///   "libx265", "aac", "libmp3lame", "libopus"). `None` = stream copy
///   (track itu disalin apa adanya, gak di-encode ulang).
/// - `video_bitrate`/`audio_bitrate`: dalam bit per detik, cuma berlaku
///   kalau track itu di-transcode (diabaikan kalau stream copy).
/// - `drop_video`/`drop_audio`: buang track itu sepenuhnya dari output
///   (mis. `drop_video=true` buat ekstrak audio doang dari file video).
/// - `trim_start`/`trim_end`: [BARU] potong media ke rentang waktu
///   tertentu (detik, absolut dari awal file sumber). Timeline output
///   di-nol-in ulang mulai dari `trim_start` (jadi output selalu mulai
///   dari pts=0, bukan dari `trim_start` aslinya). Kalau kedua-duanya
///   `None`, seluruh file dikonversi apa adanya (perilaku lama, gak
///   berubah). CATATAN: buat track yang di-stream-copy, potongannya
///   "cepat tapi kasar" -- pemotongan lompat ke keyframe terdekat
///   SEBELUM `trim_start` (gak bisa presisi frame tanpa re-encode, sama
///   kayak batasan `ffmpeg -ss` sebelum `-i`). Buat presisi frame-exact,
///   pakai `video_codec`/`audio_codec` (mode transcode).
///
/// CATATAN buat Nadia: fungsi ini nulis manual lewat API encoder
/// ffmpeg-next (bukan spawn ffmpeg.exe kayak Macan Converter sekarang).
/// Nama-nama method encoder (`open_as`, `set_flags`, dll) kadang beda
/// dikit antar versi minor ffmpeg-next -- kalau `cargo check` komplen di
/// bagian ini, cek `cargo doc --open -p ffmpeg-next` dulu match sama versi
/// 7.1 yang kepasang, jangan asal tebak nama method-nya.
/// [BARU] `progress_callback`: opsional, callable Python `fn(percent: f64)`
/// yang dipanggil berkala (di-throttle ~tiap progress maju 0.5%) selama
/// proses berjalan, plus sekali terakhir dengan `100.0` pas selesai. Dipakai
/// AudioConversionWorker (macan_audio_converter.py) buat nge-update progress
/// bar beneran, gantiin behavior lama yang cuma lompat 0% -> 100%. Persentase
/// dihitung dari posisi pts packet TERBARU yang diproses dibanding total
/// durasi (atau rentang trim_start/trim_end kalau dipakai) -- estimasi
/// berbasis timestamp container, bukan progress encoder yang presisi, tapi
/// cukup akurat buat UI progress bar. Kalau durasi gak diketahui (mis. live
/// stream/container aneh), callback gak pernah dipanggil sama sekali --
/// caller sebaiknya fallback ke indikator "sedang berjalan" tanpa persentase.
#[pyfunction]
#[pyo3(signature = (input_path, output_path, video_codec=None, audio_codec=None, video_bitrate=None, audio_bitrate=None, drop_video=false, drop_audio=false, trim_start=None, trim_end=None, progress_callback=None))]
fn convert_media(
    py: Python<'_>,
    input_path: &str,
    output_path: &str,
    video_codec: Option<&str>,
    audio_codec: Option<&str>,
    video_bitrate: Option<i64>,
    audio_bitrate: Option<i64>,
    drop_video: bool,
    drop_audio: bool,
    trim_start: Option<f64>,
    trim_end: Option<f64>,
    progress_callback: Option<Py<PyAny>>,
) -> PyResult<()> {
    init_ffmpeg()?;

    let in_path = Path::new(input_path);
    let mut ictx = ffmpeg_next::format::input(&in_path)
        .map_err(|e| PyIOError::new_err(format!("Buka file input: {}", e)))?;

    let vidx = if !drop_video {
        ictx.streams().best(ffmpeg_next::media::Type::Video).map(|s| s.index())
    } else { None };
    let aidx = if !drop_audio {
        ictx.streams().best(ffmpeg_next::media::Type::Audio).map(|s| s.index())
    } else { None };

    if vidx.is_none() && aidx.is_none() {
        return Err(PyValueError::new_err("Tidak ada track video/audio yang bisa dikonversi (cek drop_video/drop_audio)"));
    }

    // [BARU] Total durasi (detik) buat basis hitung persentase progress.
    // `ictx.duration()` balikin AV_TIME_BASE units (mikrodetik) di
    // ffmpeg-next, <= 0 kalau gak diketahui (container tanpa duration
    // header, live stream, dll) -- di kasus itu progress_span jadi 0.0 dan
    // callback progress otomatis gak pernah kepanggil sama sekali di bawah.
    let total_duration_secs: f64 = {
        let d = ictx.duration();
        if d > 0 { d as f64 / 1_000_000.0 } else { 0.0 }
    };
    // Kalau trim aktif, progress dihitung relatif ke rentang trim_start..
    // trim_end (bukan 0..total_duration) -- biar progress bar gak "nyangkut"
    // di 0% lama pas trim_start jauh dari awal, atau gak pernah nyampe 100%
    // kalau trim_end < total_duration.
    let progress_offset = trim_start.unwrap_or(0.0);
    let progress_span = match (trim_start, trim_end) {
        (_, Some(end)) if end > progress_offset => end - progress_offset,
        _ if total_duration_secs > progress_offset => total_duration_secs - progress_offset,
        _ => 0.0,
    };
    let mut last_reported_pct: f64 = -1.0; // -1 biar laporan pertama (0%) pasti kekirim

    if let Some(start) = trim_start {
        // Seek demuxer sebelum mulai baca paket. Cuma "ancang-ancang" ke
        // keyframe terdekat -- offset presisi ke pts absolut ditangani per
        // track lewat base_pts di VideoLine/AudioLine (lihat handle_packet).
        let ts = av_time_base_ts(start);
        let _ = ictx.seek(ts, ..ts);
    }
    let trim_active = trim_start.is_some() || trim_end.is_some();

    let out_path = Path::new(output_path);
    let mut octx = ffmpeg_next::format::output(&out_path)
        .map_err(|e| PyIOError::new_err(format!("Buat file output: {}", e)))?;
    let global_header = needs_global_header(&octx);

    // ── Setup track video ──
    let mut video_line: Option<VideoLine> = None;
    if let Some(idx) = vidx {
        let istream = ictx.stream(idx).unwrap();
        let in_tb = istream.time_base();
        let params = istream.parameters();

        if let Some(codec_name) = video_codec {
            // Transcode: decoder sumber -> scaler ke YUV420P (format paling
            // universal didukung encoder umum: x264/x265/mpeg4/vp9) -> encoder.
            let decoder = ffmpeg_next::codec::context::Context::from_parameters(params)
                .map_err(|e| PyRuntimeError::new_err(format!("Konteks dekoder video: {}", e)))?
                .decoder().video()
                .map_err(|e| PyRuntimeError::new_err(format!("Buat dekoder video: {}", e)))?;

            let codec = ffmpeg_next::encoder::find_by_name(codec_name)
                .ok_or_else(|| PyValueError::new_err(format!("Encoder video '{}' tidak ditemukan/tidak dikompilasi di FFmpeg", codec_name)))?;

            let mut ost = octx.add_stream(codec)
                .map_err(|e| PyRuntimeError::new_err(format!("Tambah stream video: {}", e)))?;

            let fps = decoder.frame_rate().unwrap_or(ffmpeg_next::Rational(25, 1));
            let mut enc = ffmpeg_next::codec::context::Context::new_with_codec(codec)
                .encoder().video()
                .map_err(|e| PyRuntimeError::new_err(format!("Buat encoder video: {}", e)))?;
            enc.set_width(decoder.width());
            enc.set_height(decoder.height());
            enc.set_format(ffmpeg_next::util::format::Pixel::YUV420P);
            enc.set_time_base(fps.invert());
            enc.set_frame_rate(Some(fps));
            if let Some(br) = video_bitrate {
                enc.set_bit_rate(br as usize);
            }
            if global_header {
                enc.set_flags(ffmpeg_next::codec::flag::Flags::GLOBAL_HEADER);
            }
            let encoder = enc.open_as(codec)
                .map_err(|e| PyRuntimeError::new_err(format!("Buka encoder video: {}", e)))?;
            ost.set_parameters(&encoder);

            let scaler = ffmpeg_next::software::scaling::Context::get(
                decoder.format(), decoder.width(), decoder.height(),
                ffmpeg_next::util::format::Pixel::YUV420P, decoder.width(), decoder.height(),
                ffmpeg_next::software::scaling::flag::Flags::BILINEAR,
            ).map_err(|e| PyRuntimeError::new_err(format!("Buat scaler video: {}", e)))?;

            video_line = Some(VideoLine {
                in_index: idx,
                out_index: ost.index(),
                in_tb,
                out_tb: ost.time_base(),
                in_tb_f64: rational_to_f64(in_tb),
                base_pts: None,
                shift_active: trim_active,
                trim_end_sec: trim_end,
                done: false,
                mode: TranscodeMode::Encode {
                    decoder, encoder, scaler,
                },
            });
        } else {
            // Stream copy (remux) -- pola persis contoh remux.rs resmi
            // ffmpeg-next: add_stream(None-codec), lalu set_parameters()
            // langsung dari parameter stream input, tanpa decode sama sekali.
            let mut ost = octx.add_stream(ffmpeg_next::encoder::find(ffmpeg_next::codec::Id::None))
                .map_err(|e| PyRuntimeError::new_err(format!("Tambah stream video (copy): {}", e)))?;
            ost.set_parameters(params);
            video_line = Some(VideoLine {
                in_index: idx,
                out_index: ost.index(),
                in_tb,
                out_tb: istream.time_base(),
                in_tb_f64: rational_to_f64(in_tb),
                base_pts: None,
                shift_active: trim_active,
                trim_end_sec: trim_end,
                done: false,
                mode: TranscodeMode::Copy,
            });
        }
    }

    // ── Setup track audio ──
    let mut audio_line: Option<AudioLine> = None;
    if let Some(idx) = aidx {
        let istream = ictx.stream(idx).unwrap();
        let in_tb = istream.time_base();
        let params = istream.parameters();

        if let Some(codec_name) = audio_codec {
            let decoder = ffmpeg_next::codec::context::Context::from_parameters(params)
                .map_err(|e| PyRuntimeError::new_err(format!("Konteks dekoder audio: {}", e)))?
                .decoder().audio()
                .map_err(|e| PyRuntimeError::new_err(format!("Buat dekoder audio: {}", e)))?;

            let codec = ffmpeg_next::encoder::find_by_name(codec_name)
                .ok_or_else(|| PyValueError::new_err(format!("Encoder audio '{}' tidak ditemukan/tidak dikompilasi di FFmpeg", codec_name)))?;

            let mut ost = octx.add_stream(codec)
                .map_err(|e| PyRuntimeError::new_err(format!("Tambah stream audio: {}", e)))?;

            let out_rate = decoder.rate();
            let out_layout = if decoder.channel_layout().bits() != 0 {
                decoder.channel_layout()
            } else {
                ffmpeg_next::util::channel_layout::ChannelLayout::default(decoder.channels() as i32)
            };

            let mut enc = ffmpeg_next::codec::context::Context::new_with_codec(codec)
                .encoder().audio()
                .map_err(|e| PyRuntimeError::new_err(format!("Buat encoder audio: {}", e)))?;
            enc.set_rate(out_rate as i32);
            enc.set_channel_layout(out_layout);
            enc.set_format(ffmpeg_next::util::format::Sample::F32(ffmpeg_next::util::format::sample::Type::Planar));
            enc.set_time_base(ffmpeg_next::Rational(1, out_rate as i32));
            if let Some(br) = audio_bitrate {
                enc.set_bit_rate(br as usize);
            }
            if global_header {
                enc.set_flags(ffmpeg_next::codec::flag::Flags::GLOBAL_HEADER);
            }
            let encoder = enc.open_as(codec)
                .map_err(|e| PyRuntimeError::new_err(format!("Buka encoder audio: {}", e)))?;
            ost.set_parameters(&encoder);

            // [BARU] Ambil jumlah channel encoder SEBELUM `encoder` dipindah
            // (moved) ke dalam AudioTranscodeMode::Encode di bawah -- dipakai
            // buat inisialisasi AudioFifo.
            let enc_channels = encoder.channels() as usize;

            let resampler = ffmpeg_next::software::resampling::Context::get(
                decoder.format(), decoder.channel_layout(), decoder.rate(),
                encoder.format(), encoder.channel_layout(), encoder.rate(),
            ).map_err(|e| PyRuntimeError::new_err(format!("Buat resampler audio: {}", e)))?;

            audio_line = Some(AudioLine {
                in_index: idx,
                out_index: ost.index(),
                in_tb,
                out_tb: ost.time_base(),
                in_tb_f64: rational_to_f64(in_tb),
                base_pts: None,
                shift_active: trim_active,
                trim_end_sec: trim_end,
                done: false,
                mode: AudioTranscodeMode::Encode {
                    decoder, encoder, resampler,
                    fifo: AudioFifo::new(enc_channels),
                    next_pts: 0,
                },
            });
        } else {
            let mut ost = octx.add_stream(ffmpeg_next::encoder::find(ffmpeg_next::codec::Id::None))
                .map_err(|e| PyRuntimeError::new_err(format!("Tambah stream audio (copy): {}", e)))?;
            ost.set_parameters(params);
            audio_line = Some(AudioLine {
                in_index: idx,
                out_index: ost.index(),
                in_tb,
                out_tb: istream.time_base(),
                in_tb_f64: rational_to_f64(in_tb),
                base_pts: None,
                shift_active: trim_active,
                trim_end_sec: trim_end,
                done: false,
                mode: AudioTranscodeMode::Copy,
            });
        }
    }

    octx.write_header()
        .map_err(|e| PyRuntimeError::new_err(format!("Tulis header output: {}", e)))?;

    // [PENTING] Refresh out_tb SETELAH write_header(), BUKAN sebelumnya.
    // Sebagian muxer (mis. MP4) suka nimpa/finalize time_base stream pas
    // avformat_write_header() dipanggil -- kalau out_tb yang dipake buat
    // rescale_ts() masih nilai lama (dari sebelum header ditulis), paket
    // yang ditulis bisa salah timing di kontainer akhir.
    if let Some(vl) = video_line.as_mut() {
        vl.out_tb = octx.stream(vl.out_index).unwrap().time_base();
    }
    if let Some(al) = audio_line.as_mut() {
        al.out_tb = octx.stream(al.out_index).unwrap().time_base();
    }

    // ── Loop utama: demux paket, salurkan ke jalur video/audio yang cocok ──
    for (stream, mut packet) in ictx.packets() {
        let sidx = stream.index();
        if let Some(vl) = video_line.as_mut() {
            if sidx == vl.in_index {
                vl.handle_packet(&mut packet, &mut octx)?;
            }
        }
        if let Some(al) = audio_line.as_mut() {
            if sidx == al.in_index {
                al.handle_packet(&mut packet, &mut octx)?;
            }
        }
        // Track lain (subtitle dll) sengaja diabaikan -- converter ini
        // fokus audio/video doang, sama kayak scope Macan Converter yang
        // sekarang.

        // [BARU] Report progress berdasarkan posisi pts packet TERBARU yang
        // baru diproses. Di-throttle: cuma manggil balik ke Python (call1,
        // yang jalan minimal 1 alokasi + acquire ke Python bytecode eval)
        // kalau progress udah maju >= 0.5% dari laporan sebelumnya --
        // tanpa throttle ini, file yang banyak paketnya bisa manggil
        // callback ribuan kali/detik dan bikin overhead gak perlu.
        if let (Some(cb), true) = (progress_callback.as_ref(), progress_span > 0.0) {
            if let Some(ts) = packet.pts().or_else(|| packet.dts()) {
                let sec = ts as f64 * rational_to_f64(stream.time_base());
                let pct = ((sec - progress_offset) / progress_span * 100.0).clamp(0.0, 100.0);
                if pct - last_reported_pct >= 0.5 {
                    last_reported_pct = pct;
                    let _ = cb.call1(py, (pct,));
                }
            }
        }

        // [BARU] Kalau trim_end dipasang, tiap line nandain dirinya
        // `done` begitu ngelewatin trim_end. Begitu SEMUA line yang
        // aktif udah done, berhenti demux -- gak perlu baca sisa file.
        let v_done = video_line.as_ref().map(|l| l.done).unwrap_or(true);
        let a_done = audio_line.as_ref().map(|l| l.done).unwrap_or(true);
        if v_done && a_done {
            break;
        }
    }

    // ── Flush: drain decoder+encoder yang masih nyimpen frame/paket ──
    if let Some(vl) = video_line.as_mut() {
        vl.flush(&mut octx)?;
    }
    if let Some(al) = audio_line.as_mut() {
        al.flush(&mut octx)?;
    }

    octx.write_trailer()
        .map_err(|e| PyRuntimeError::new_err(format!("Tulis trailer output: {}", e)))?;

    // [BARU] Laporan terakhir -- pastikan UI selalu nampilin persis 100%
    // pas selesai, walau pts packet terakhir yang ke-throttle di atas
    // kebetulan berhenti sebelum benar-benar nyentuh progress_span penuh
    // (mis. karena rounding, atau container yang durasi headernya meleset
    // dikit dari total pts paket sebenarnya).
    if let Some(cb) = progress_callback.as_ref() {
        let _ = cb.call1(py, (100.0_f64,));
    }

    Ok(())
}

enum TranscodeMode {
    Copy,
    Encode {
        decoder: ffmpeg_next::decoder::Video,
        encoder: ffmpeg_next::encoder::Video,
        scaler: ffmpeg_next::software::scaling::Context,
    },
}

struct VideoLine {
    in_index: usize,
    out_index: usize,
    in_tb: ffmpeg_next::Rational,
    out_tb: ffmpeg_next::Rational,
    in_tb_f64: f64,
    // [BARU] Dukungan trim -- lihat catatan lengkap di dokumentasi
    // convert_media(). base_pts = pts (dalam tick in_tb) dari paket
    // PERTAMA yang lewat sini setelah seek; semua paket berikutnya
    // digeser relatif ke ini biar output mulai dari pts=0.
    base_pts: Option<i64>,
    shift_active: bool,
    trim_end_sec: Option<f64>,
    done: bool,
    mode: TranscodeMode,
}

impl VideoLine {
    fn handle_packet(&mut self, packet: &mut ffmpeg_next::Packet, octx: &mut ffmpeg_next::format::context::Output) -> PyResult<()> {
        if self.done {
            return Ok(());
        }

        // [BARU] Cek trim_end SEBELUM digeser -- perbandingannya harus ke
        // posisi ABSOLUT di file asli, bukan posisi yang udah di-nol-in.
        if let Some(end_sec) = self.trim_end_sec {
            let raw_ts = packet.pts().or_else(|| packet.dts()).unwrap_or(0);
            if (raw_ts as f64) * self.in_tb_f64 > end_sec {
                self.done = true;
                return Ok(());
            }
        }

        // [BARU] Geser pts/dts biar timeline output mulai dari 0, cuma
        // aktif kalau trim beneran dipake (trim_start/trim_end) -- kalau
        // enggak, paket dipake apa adanya, sama kayak sebelum ada trim.
        if self.shift_active {
            let raw_ts = packet.pts().or_else(|| packet.dts()).unwrap_or(0);
            let base = *self.base_pts.get_or_insert(raw_ts);
            packet.set_pts(packet.pts().map(|p| p - base));
            packet.set_dts(packet.dts().map(|d| d - base));
        }

        match &mut self.mode {
            TranscodeMode::Copy => {
                packet.rescale_ts(self.in_tb, self.out_tb);
                packet.set_stream(self.out_index);
                packet.write_interleaved(octx)
                    .map_err(|e| PyRuntimeError::new_err(format!("Tulis paket video: {}", e)))?;
            }
            TranscodeMode::Encode { decoder, encoder, scaler } => {
                decoder.send_packet(packet)
                    .map_err(|e| PyRuntimeError::new_err(format!("Kirim paket video ke decoder: {}", e)))?;
                let mut decoded = ffmpeg_next::frame::Video::empty();
                while decoder.receive_frame(&mut decoded).is_ok() {
                    let mut scaled = ffmpeg_next::frame::Video::empty();
                    scaler.run(&decoded, &mut scaled)
                        .map_err(|e| PyRuntimeError::new_err(format!("Scale frame video: {}", e)))?;
                    scaled.set_pts(decoded.pts());
                    encoder.send_frame(&scaled)
                        .map_err(|e| PyRuntimeError::new_err(format!("Kirim frame video ke encoder: {}", e)))?;
                    Self::drain_encoder(encoder, self.out_index, self.out_tb, octx)?;
                }
            }
        }
        Ok(())
    }

    fn drain_encoder(
        encoder: &mut ffmpeg_next::encoder::Video,
        out_index: usize,
        out_tb: ffmpeg_next::Rational,
        octx: &mut ffmpeg_next::format::context::Output,
    ) -> PyResult<()> {
        let mut enc_pkt = ffmpeg_next::Packet::empty();
        while encoder.receive_packet(&mut enc_pkt).is_ok() {
            enc_pkt.set_stream(out_index);
            enc_pkt.rescale_ts(encoder.time_base(), out_tb);
            enc_pkt.write_interleaved(octx)
                .map_err(|e| PyRuntimeError::new_err(format!("Tulis paket video hasil encode: {}", e)))?;
        }
        Ok(())
    }

    fn flush(&mut self, octx: &mut ffmpeg_next::format::context::Output) -> PyResult<()> {
        if let TranscodeMode::Encode { decoder, encoder, scaler } = &mut self.mode {
            let _ = decoder.send_eof();
            let mut decoded = ffmpeg_next::frame::Video::empty();
            while decoder.receive_frame(&mut decoded).is_ok() {
                let mut scaled = ffmpeg_next::frame::Video::empty();
                if scaler.run(&decoded, &mut scaled).is_ok() {
                    scaled.set_pts(decoded.pts());
                    let _ = encoder.send_frame(&scaled);
                    Self::drain_encoder(encoder, self.out_index, self.out_tb, octx)?;
                }
            }
            let _ = encoder.send_eof();
            Self::drain_encoder(encoder, self.out_index, self.out_tb, octx)?;
        }
        Ok(())
    }
}

/// [BARU] Buffer sample audio antar frame resampled -> encoder frame_size.
/// Root cause bug "Kirim frame audio ke encoder: Invalid argument" pas
/// convert m4a(AAC) -> mp3: decoder AAC menghasilkan 1024 sample/frame,
/// TAPI libmp3lame WAJIB persis 1152 sample per frame (kecuali frame
/// terakhir) -- ini bukan variable-frame-size codec. Kirim frame dengan
/// nb_samples yang gak match avctx->frame_size bikin avcodec_send_frame()
/// balikin AVERROR(EINVAL) alias "Invalid argument". Kebetulan mp3->mp3
/// "kerja" karena decode MP3 juga persis 1152 sample/frame, jadi gak
/// pernah nabrak masalah rechunking ini.
///
/// FIFO ini nampung sample float32 per-channel-plane (encoder SELALU
/// dikonfigurasi format F32 Planar, lihat setup di bawah), lalu ngeluarin
/// chunk PERSIS `frame_size` sample tiap kali cukup -- generik buat semua
/// encoder (frame_size==0 buat codec variable-size kayak PCM ditangani
/// terpisah, lihat drain_fifo()).
struct AudioFifo {
    channels: usize,
    buf: Vec<Vec<f32>>,
}

impl AudioFifo {
    fn new(channels: usize) -> Self {
        AudioFifo { channels, buf: (0..channels).map(|_| Vec::new()).collect() }
    }

    /// Salin seluruh sample dari 1 frame F32 Planar ke buffer internal.
    fn push(&mut self, frame: &ffmpeg_next::frame::Audio) {
        if frame.samples() == 0 {
            return;
        }
        for ch in 0..self.channels.min(frame.planes()) {
            let plane: &[f32] = frame.plane(ch);
            self.buf[ch].extend_from_slice(plane);
        }
    }

    /// Jumlah sample yang siap diambil (sama buat semua channel).
    fn available(&self) -> usize {
        self.buf.first().map(|v| v.len()).unwrap_or(0)
    }

    /// Ambil persis `n` sample per channel (n <= available()), bikin frame
    /// F32 Planar baru buat dikirim ke encoder.
    fn pop_frame(
        &mut self,
        n: usize,
        layout: ffmpeg_next::util::channel_layout::ChannelLayout,
        rate: u32,
    ) -> ffmpeg_next::frame::Audio {
        let mut out = ffmpeg_next::frame::Audio::new(
            ffmpeg_next::util::format::Sample::F32(ffmpeg_next::util::format::sample::Type::Planar),
            n,
            layout,
        );
        out.set_rate(rate);
        for ch in 0..self.channels {
            let dst: &mut [f32] = out.plane_mut(ch);
            dst.copy_from_slice(&self.buf[ch][..n]);
            self.buf[ch].drain(..n);
        }
        out
    }
}

enum AudioTranscodeMode {
    Copy,
    Encode {
        decoder: ffmpeg_next::decoder::Audio,
        encoder: ffmpeg_next::encoder::Audio,
        resampler: ffmpeg_next::software::resampling::Context,
        // [BARU] Lihat AudioFifo -- rechunk sample resampled ke persis
        // encoder.frame_size() sebelum di-encoder.send_frame().
        fifo: AudioFifo,
        next_pts: i64,
    },
}

struct AudioLine {
    in_index: usize,
    out_index: usize,
    in_tb: ffmpeg_next::Rational,
    out_tb: ffmpeg_next::Rational,
    in_tb_f64: f64,
    base_pts: Option<i64>,
    shift_active: bool,
    trim_end_sec: Option<f64>,
    done: bool,
    mode: AudioTranscodeMode,
}

impl AudioLine {
    fn handle_packet(&mut self, packet: &mut ffmpeg_next::Packet, octx: &mut ffmpeg_next::format::context::Output) -> PyResult<()> {
        if self.done {
            return Ok(());
        }

        if let Some(end_sec) = self.trim_end_sec {
            let raw_ts = packet.pts().or_else(|| packet.dts()).unwrap_or(0);
            if (raw_ts as f64) * self.in_tb_f64 > end_sec {
                self.done = true;
                return Ok(());
            }
        }

        if self.shift_active {
            let raw_ts = packet.pts().or_else(|| packet.dts()).unwrap_or(0);
            let base = *self.base_pts.get_or_insert(raw_ts);
            packet.set_pts(packet.pts().map(|p| p - base));
            packet.set_dts(packet.dts().map(|d| d - base));
        }

        match &mut self.mode {
            AudioTranscodeMode::Copy => {
                packet.rescale_ts(self.in_tb, self.out_tb);
                packet.set_stream(self.out_index);
                packet.write_interleaved(octx)
                    .map_err(|e| PyRuntimeError::new_err(format!("Tulis paket audio: {}", e)))?;
            }
            AudioTranscodeMode::Encode { decoder, encoder, resampler, fifo, next_pts } => {
                decoder.send_packet(packet)
                    .map_err(|e| PyRuntimeError::new_err(format!("Kirim paket audio ke decoder: {}", e)))?;
                let mut decoded = ffmpeg_next::frame::Audio::empty();
                while decoder.receive_frame(&mut decoded).is_ok() {
                    let mut resampled = ffmpeg_next::frame::Audio::empty();
                    if resampler.run(&decoded, &mut resampled).is_ok() {
                        // [FIX] JANGAN langsung encoder.send_frame(&resampled)
                        // -- jumlah sample hasil resample (ngikutin ukuran
                        // frame decoder, mis. 1024 buat AAC) belum tentu
                        // sama dengan encoder.frame_size() (mis. 1152 buat
                        // mp3). Numpuk dulu ke fifo, baru kirim per-chunk
                        // persis frame_size (lihat AudioFifo di atas).
                        fifo.push(&resampled);
                        let frame_size = encoder.frame_size() as usize;
                        let layout = encoder.channel_layout();
                        let rate = encoder.rate();
                        Self::drain_fifo(
                            fifo, encoder, frame_size, false,
                            layout, rate, next_pts,
                            self.out_index, self.out_tb, octx,
                        )?;
                    }
                }
            }
        }
        Ok(())
    }

    fn drain_encoder(
        encoder: &mut ffmpeg_next::encoder::Audio,
        out_index: usize,
        out_tb: ffmpeg_next::Rational,
        octx: &mut ffmpeg_next::format::context::Output,
    ) -> PyResult<()> {
        let mut enc_pkt = ffmpeg_next::Packet::empty();
        while encoder.receive_packet(&mut enc_pkt).is_ok() {
            enc_pkt.set_stream(out_index);
            enc_pkt.rescale_ts(encoder.time_base(), out_tb);
            enc_pkt.write_interleaved(octx)
                .map_err(|e| PyRuntimeError::new_err(format!("Tulis paket audio hasil encode: {}", e)))?;
        }
        Ok(())
    }

    /// [BARU] Kosongin AudioFifo -> kirim ke encoder dalam chunk yang PAS
    /// buat codec ini. Dua mode:
    ///   - frame_size > 0 (mis. mp3=1152, aac=1024): kirim per-chunk PERSIS
    ///     frame_size sample. Sisa < frame_size dibiarkan numpuk di fifo
    ///     KECUALI `force_final` true (dipanggil pas flush/EOF) -- baru di
    ///     situ sisa terakhir ini dikirim sebagai frame lebih kecil (encoder
    ///     modern umumnya support CODEC_CAP_SMALL_LAST_FRAME buat kasus ini,
    ///     termasuk mp3/aac/vorbis).
    ///   - frame_size == 0 (mis. pcm_s16le, "variable frame size"): gak ada
    ///     yang perlu di-rechunk, langsung kosongin semua yang numpuk jadi
    ///     satu frame apa adanya, sama kayak perilaku lama.
    fn drain_fifo(
        fifo: &mut AudioFifo,
        encoder: &mut ffmpeg_next::encoder::Audio,
        frame_size: usize,
        force_final: bool,
        layout: ffmpeg_next::util::channel_layout::ChannelLayout,
        rate: u32,
        next_pts: &mut i64,
        out_index: usize,
        out_tb: ffmpeg_next::Rational,
        octx: &mut ffmpeg_next::format::context::Output,
    ) -> PyResult<()> {
        if frame_size == 0 {
            let n = fifo.available();
            if n > 0 {
                let mut out_frame = fifo.pop_frame(n, layout, rate);
                out_frame.set_pts(Some(*next_pts));
                *next_pts += n as i64;
                encoder.send_frame(&out_frame)
                    .map_err(|e| PyRuntimeError::new_err(format!("Kirim frame audio ke encoder: {}", e)))?;
                Self::drain_encoder(encoder, out_index, out_tb, octx)?;
            }
            return Ok(());
        }

        while fifo.available() >= frame_size {
            let mut out_frame = fifo.pop_frame(frame_size, layout, rate);
            out_frame.set_pts(Some(*next_pts));
            *next_pts += frame_size as i64;
            encoder.send_frame(&out_frame)
                .map_err(|e| PyRuntimeError::new_err(format!("Kirim frame audio ke encoder: {}", e)))?;
            Self::drain_encoder(encoder, out_index, out_tb, octx)?;
        }

        if force_final {
            let n = fifo.available();
            if n > 0 {
                let mut out_frame = fifo.pop_frame(n, layout, rate);
                out_frame.set_pts(Some(*next_pts));
                *next_pts += n as i64;
                // best-effort, sama kayak flush() lain di file ini (`let _ =`)
                // -- codec yang gak support small-last-frame tinggal drop
                // sisa < 1 frame_size ini, bukan hard error pas aplikasi
                // lagi exit/selesai.
                let _ = encoder.send_frame(&out_frame);
                Self::drain_encoder(encoder, out_index, out_tb, octx)?;
            }
        }
        Ok(())
    }

    fn flush(&mut self, octx: &mut ffmpeg_next::format::context::Output) -> PyResult<()> {
        if let AudioTranscodeMode::Encode { decoder, encoder, resampler, fifo, next_pts } = &mut self.mode {
            let _ = decoder.send_eof();
            let mut decoded = ffmpeg_next::frame::Audio::empty();
            while decoder.receive_frame(&mut decoded).is_ok() {
                let mut resampled = ffmpeg_next::frame::Audio::empty();
                if resampler.run(&decoded, &mut resampled).is_ok() {
                    fifo.push(&resampled);
                    let frame_size = encoder.frame_size() as usize;
                    let layout = encoder.channel_layout();
                    let rate = encoder.rate();
                    Self::drain_fifo(
                        fifo, encoder, frame_size, false,
                        layout, rate, next_pts,
                        self.out_index, self.out_tb, octx,
                    )?;
                }
            }
            // [FIX] Kosongin sisa terakhir yang numpuk di fifo (< frame_size,
            // gak akan pernah lolos syarat `fifo.available() >= frame_size`
            // di loop normal manapun) SEBELUM encoder.send_eof() -- tanpa
            // ini, ekor terakhir audio (< 1 frame_size sample) bakal ke-drop
            // diam-diam alih-alih ikut ke-encode.
            let frame_size = encoder.frame_size() as usize;
            let layout = encoder.channel_layout();
            let rate = encoder.rate();
            Self::drain_fifo(
                fifo, encoder, frame_size, true,
                layout, rate, next_pts,
                self.out_index, self.out_tb, octx,
            )?;
            let _ = encoder.send_eof();
            Self::drain_encoder(encoder, self.out_index, self.out_tb, octx)?;
        }
        Ok(())
    }
}

// ═══════════════════════════════════════════════
// BAGIAN 6: UTILITAS MULTIMEDIA TAMBAHAN -- thumbnail grid & loudness.
// Sama-sama "decode sekali, dapet hasil sekaligus", cocok buat kebutuhan
// UI kayak grid preview di media library / normalize volume di
// converter/audio tools.
// ═══════════════════════════════════════════════

/// [BARU] Ambil beberapa thumbnail sekaligus dari video, disebar merata
/// sepanjang durasi (posisi ke-i ada di tengah segmen ke-i, biar gak
/// kejebak di frame item hitam persis detik 0 / gagal decode persis EOF).
/// Beda dari VideoDecoder.seek_frame() (BAGIAN 2) yang satu-satu & scaler-nya
/// terpatok ukuran asli video -- di sini scaler dibikin SEKALI di ukuran
/// thumbnail (bisa diresize via `max_width`) lalu dipakai ulang buat semua
/// posisi, jadi jauh lebih murah buat generate banyak sekaligus (mis. buat
/// grid preview di file browser Macan Movie Pro).
///
/// Balikin list `(array_rgb, pts_detik)`. Thumbnail yang gagal di-seek/decode
/// (kadang kejadian di file yang korup sebagian) dilewatin diam-diam, BUKAN
/// bikin seluruh fungsi gagal -- lebih baik dapet grid yang bolong dikit
/// drpd gagal total gara-gara 1 dari N thumbnail bermasalah.
#[pyfunction]
#[pyo3(signature = (file_path, count, max_width=None))]
fn generate_thumbnails(
    py: Python<'_>,
    file_path: &str,
    count: usize,
    max_width: Option<u32>,
) -> PyResult<Vec<(Py<PyArray3<u8>>, f64)>> {
    if count == 0 {
        return Ok(Vec::new());
    }
    init_ffmpeg()?;

    let path = Path::new(file_path);
    let mut input_ctx = ffmpeg_next::format::input(&path)
        .map_err(|e| PyIOError::new_err(format!("Buka file: {}", e)))?;
    let stream = input_ctx.streams().best(ffmpeg_next::media::Type::Video)
        .ok_or_else(|| PyValueError::new_err("Tidak ada aliran video"))?;
    let stream_idx = stream.index();
    let time_base = rational_to_f64(stream.time_base());
    let duration = stream.duration() as f64 * time_base;

    let ctx = ffmpeg_next::codec::context::Context::from_parameters(stream.parameters())
        .map_err(|e| PyRuntimeError::new_err(format!("Konteks dekoder: {}", e)))?;
    let mut decoder = ctx.decoder().video()
        .map_err(|e| PyRuntimeError::new_err(format!("Buat dekoder: {}", e)))?;
    let src_format = decoder.format();
    let (src_w, src_h) = (decoder.width(), decoder.height());

    if duration <= 0.0 || src_w == 0 || src_h == 0 {
        return Err(PyValueError::new_err("Durasi/dimensi video tidak valid, gak bisa generate thumbnail"));
    }

    // Hitung dimensi thumbnail -- jaga aspect ratio, dibulatin ke genap
    // (banyak scaler/pixel format gak suka dimensi ganjil).
    let (dst_w, dst_h) = match max_width {
        Some(mw) if mw > 0 && mw < src_w => {
            let ratio = mw as f64 / src_w as f64;
            let h = (((src_h as f64 * ratio) as u32) & !1).max(2);
            (mw & !1, h)
        }
        _ => (src_w, src_h),
    };

    let mut scaler = ffmpeg_next::software::scaling::Context::get(
        src_format, src_w, src_h,
        ffmpeg_next::util::format::Pixel::RGB24, dst_w, dst_h,
        ffmpeg_next::software::scaling::flag::Flags::BILINEAR,
    ).map_err(|e| PyRuntimeError::new_err(format!("Buat scaler thumbnail: {}", e)))?;

    let mut results: Vec<(Py<PyArray3<u8>>, f64)> = Vec::with_capacity(count);
    let mut decoded = ffmpeg_next::frame::Video::empty();

    for i in 0..count {
        let second = duration * (i as f64 + 0.5) / count as f64;
        let seek_ts = av_time_base_ts(second);
        let target_ts = (second / time_base).round() as i64;

        if input_ctx.seek(seek_ts, ..seek_ts).is_err() {
            continue; // lewatin thumbnail ini, jangan gagalin semuanya
        }
        decoder.flush();

        let mut got_frame = false;
        let mut packet_count = 0;
        'search: for (s, packet) in input_ctx.packets() {
            if packet_count > 200 { break; }
            if s.index() != stream_idx {
                packet_count += 1;
                continue;
            }
            if decoder.send_packet(&packet).is_err() {
                packet_count += 1;
                continue;
            }
            while decoder.receive_frame(&mut decoded).is_ok() {
                got_frame = true;
                if decoded.timestamp().unwrap_or(0) >= target_ts {
                    break 'search;
                }
            }
            packet_count += 1;
        }
        if !got_frame {
            continue;
        }

        let mut rgb_frame = ffmpeg_next::frame::Video::new(
            ffmpeg_next::util::format::Pixel::RGB24, dst_w, dst_h,
        );
        if scaler.run(&decoded, &mut rgb_frame).is_err() {
            continue;
        }

        let stride = rgb_frame.stride(0);
        let row_width = (dst_w as usize) * 3;
        let mut data = Vec::with_capacity((dst_h as usize) * row_width);
        let raw = rgb_frame.data(0);
        for y in 0..(dst_h as usize) {
            let start = y * stride;
            data.extend_from_slice(&raw[start..start + row_width]);
        }

        let arr = match Array3::from_shape_vec((dst_h as usize, dst_w as usize, 3), data) {
            Ok(a) => a,
            Err(_) => continue,
        };
        results.push((arr.into_pyarray(py).into(), second));
    }

    Ok(results)
}

/// [BARU] Analisa loudness kasar (peak & RMS, dalam dBFS) buat 1 file
/// audio. Cocok buat fitur "normalize volume" di audio cutter/tag editor
/// atau converter -- BUKAN pengukuran EBU R128 LUFS presisi broadcast,
/// tapi cukup buat kebutuhan normalisasi umum aplikasi desktop (mis.
/// hitung berapa dB gain yang perlu ditambahin biar peak nyentuh -1dBFS).
///
/// Balikin `(peak_db, rms_db)`. Keduanya negatif atau 0 (0 dBFS = full
/// scale, makin negatif makin pelan).
#[pyfunction]
fn analyze_loudness(file_path: &str) -> PyResult<(f32, f32)> {
    let samples = decode_audio_mono(file_path, 44100)?;
    if samples.is_empty() {
        return Err(PyValueError::new_err("Tidak ada sample audio yang bisa dibaca dari file ini"));
    }

    let peak = samples.par_iter().map(|s| s.abs()).reduce(|| 0.0f32, f32::max);
    let sum_sq: f32 = samples.par_iter().map(|s| s * s).sum();
    let rms = (sum_sq / samples.len() as f32).sqrt();

    // Floor -120dB biar file yang beneran diem total (peak=0.0) gak
    // ngasilin log10(0) = -inf, yang bakal bikin masalah kalau nilainya
    // dipake buat kalkulasi gain di sisi Python (mis. -inf + apapun = -inf).
    let peak_db = 20.0 * peak.max(1e-6).log10();
    let rms_db = 20.0 * rms.max(1e-6).log10();
    Ok((peak_db, rms_db))
}

// ═══════════════════════════════════════════════
// DAFTARKAN KE MODUL
// ═══════════════════════════════════════════════

#[pymodule]
fn media_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<MediaInfo>()?;
    m.add_class::<AudioInfo>()?;
    m.add_class::<VideoDecoder>()?;
    m.add_class::<PlayerEngine>()?;
    m.add_class::<SpectrumAnalyzer>()?;
    m.add_function(wrap_pyfunction!(analyze_waveform, m)?)?;
    m.add_function(wrap_pyfunction!(convert_media, m)?)?;
    m.add_function(wrap_pyfunction!(generate_thumbnails, m)?)?;
    m.add_function(wrap_pyfunction!(analyze_loudness, m)?)?;
    m.add_function(wrap_pyfunction!(decode_audio, m)?)?;
    m.add_function(wrap_pyfunction!(compute_waveform_envelope, m)?)?;
    m.add_function(wrap_pyfunction!(detect_bpm_py, m)?)?;
    Ok(())
}
