# Kazi: Rekebisha HLS Video Conversion Pipeline (Celery + FFmpeg)

## Muktasari wa tatizo (uliogunduliwa kwa uchunguzi wa moja kwa moja kwenye production)

Video processing pipeline (`apps/streaming/tasks/tasks.py`) inatumia Celery + FFmpeg kubadilisha
video zilizopakiwa kuwa HLS multi-quality streams (1080p, 720p, 480p, 360p). Video kubwa
(GB 10+, dakika 50+) mara kwa mara zinakwama (hang) katikati ya conversion — hasa kwenye
mpito kati ya variant moja na nyingine (mfano: 1080p inakamilika, 720p inaanza, kisha
ffmpeg process inakuwa "kimya" kabisa — hakuna CPU time wala disk I/O mpya — milele, mpaka
mtu amwue kwa mkono).

Server: CPU-only (hakuna GPU), AMD EPYC vCPU cores 6, RAM ~12GB, Docker (CapRover deployment).
Container: `srv-captain--farajayangu-background-tasks-backend`.

## Ushahidi uliokusanywa (kwa uchunguzi wa `/proc/<pid>/io`, `top`, logs)

- Process ya ffmpeg ilikuwa na State `S (sleeping)` kwa zaidi ya dakika 15-20 bila mabadiliko
  YOYOTE kwenye `/proc/<pid>/io` (rchar/wchar/read_bytes/write_bytes vilivyokaa sawa kabisa
  kwenye usomaji tatu tofauti, kila mmoja ukitenganishwa kwa sekunde 15+).
- CPU time (`TIME+` kwenye `ps aux`) haikuongezeka hata sekunde moja kwa muda huo wote.
- Faili za mwisho za `.ts` segment hazikuongezeka kwa zaidi ya dakika 25.
- Tukio hili limejirudia mara mbili kwa video ile ile (video_id 491) — mara zote mbili
  baada ya variant ya 1080p kukamilika, wakati 720p inapoanza/kuendelea.
- Kwenye `celery_video_worker.log` kumeonekana pia:
  - `ConnectionError: Connection closed by server` na `Cannot connect to redis...` (21 Julai) —
    Redis broker ilipoteza uhusiano kabisa kwa dakika kadhaa.
  - `ImportError: cannot import name 'reconstruct_mp4_for_download_task'` mara 4 mfululizo
    (23 Julai 13:57-15:29) — deployment mbovu ilisababisha kila task ishindwe mara moja.
  - `RuntimeError('No active exception to reraise')` mara mbili — kutokana na bare `raise`
    ndani ya `except Exception as e:` block ya `convert_video_to_hls`.
  - `'error': 'Video not found'` — video iliyokuwa bado "in flight" (task ya awali
    haijamaliza kuiandaa) ilijaribiwa mapema mno na task nyingine (uwezekano wa
    Celery redelivery baada ya `visibility_timeout` ya masaa 4 kuisha wakati worker
    ilianguka).
- `VideoProcessor.get_recommended_parallel_workers()` ina comment inayosema
  "With threads=0 (auto), FFmpeg will use ALL available cores" lakini ffmpeg command halisi
  ina `-threads 4` iliyowekwa moja kwa moja (hardcoded) — hii haiendani na cores 6 zilizopo
  (inapoteza cores 2 kila wakati).
- `soft_time_limit=14400` (masaa 4) na `time_limit=18000` (masaa 5) ni ndefu mno kwa video
  za dakika 50-60 kwenye server ya cores 6 — Celery yenyewe haiwezi kuingilia kati task
  iliyokwama mpaka baada ya masaa 4-5.

## Faili muhimu za kuangalia

- `apps/streaming/tasks/tasks.py` — `convert_video_to_hls`, `assemble_chunks_task`,
  `cleanup_local_files`
- `apps/streaming/services/video_processor.py` — `VideoProcessor`, `_create_hls_variant`,
  `get_recommended_parallel_workers`, ffmpeg command construction (karibu na mstari 686-831)
- `apps/streaming/services/video_presets.py` — `QUALITY_PRESETS`, `get_enabled_hls_variants`
- `farajayangu_be/settings/base.py` — Celery broker settings (`visibility_timeout`,
  `retry_on_timeout`)
- `apps/streaming/services/conversion_client.py` — `trigger_video_processing`

## MALENGO (yote yanahitajika)

### 1. Watchdog ya kugundua ffmpeg iliyokwama na kuipona kiotomatiki (MUHIMU ZAIDI)

Ffmpeg tayari inatumia `-progress pipe:1`, ambayo hutoa mistari ya progress (key=value,
kwa mfano `out_time_ms=...`, `frame=...`) kila sekunde chache kwenye stdout. Sasa hivi
hii pipe HAISOMWI popote kwenye code (hivyo ffmpeg inaweza hata kuzuiwa/block ikiwa
pipe buffer imejaa bila kusomwa - hii yenyewe inaweza kuwa CHANZO cha kukwama).

Tekeleza:
- Badilisha jinsi ffmpeg subprocess inavyoendeshwa: tumia `subprocess.Popen` na usome
  stdout (`-progress pipe:1`) kwa kutumia thread tofauti isiyozuia (non-blocking read
  loop), ukirekodi wakati wa mstari wa mwisho wa progress uliopokelewa.
- Endesha "watchdog timer" (thread ya pili au `select`/`selectors` based timeout loop)
  inayoangalia: kama hakuna mstari mpya wa progress kwa zaidi ya dakika 3-5 (weka kama
  constant inayoweza kubadilishwa, mfano `FFMPEG_STALL_TIMEOUT_SECONDS = 240`), basi:
  1. Piga `process.kill()` (SIGKILL) kwenye ffmpeg subprocess na watoto wake wote
     (child processes - tumia `os.killpg` na `os.setsid` wakati wa kuanzisha Popen ili
     kuhakikisha process group nzima inauawa, si mzazi tu).
  2. Tupa exception maalum (mfano `FFmpegStalledError`) yenye ujumbe unaoeleza variant
     gani, video_id gani, na muda ulipita bila progress.
  3. Hakikisha exception hii inashughulikiwa na `convert_video_to_hls` (angalia #3 hapa
     chini kuhusu retry na checkpoint).
- Ongeza logging ya wazi: `logger.error(f"FFmpeg stalled for video {video_id} variant
  {variant_name} - no progress for {elapsed}s, killing and retrying")`.

### 2. Rekebisha `-threads` kuendana na cores halisi za server

- Badilisha `-threads 4` (hardcoded) kuwa parameter inayosomwa kutoka
  `multiprocessing.cpu_count()` (au settings variable inayoweza kubadilishwa kwa mazingira
  tofauti ya server), kwa default itumie cores zote (`-threads 0` ni sawa na "auto" kwenye
  ffmpeg/libx264, AU weka wazi `cpu_count()`).
- Hakikisha hii inaendana vizuri na ukweli kwamba `parallel_variants` tayari ni 1 (sequential)
  - kwa hiyo variant moja inapaswa kupata cores ZOTE 6, si 4.

### 3. Hakikisha checkpoint/resume inafanya kazi vizuri baada ya kill ya watchdog au crash

- Kagua `completed_variants` checkpoint logic kwenye `convert_video_to_hls` — hakikisha
  kwamba variant iliyokuwa "katikati" (mfano 720p ilikuwa imeandika segments 20 kati ya
  X) IKIONDOLEWA kabisa (folder ya variant hiyo kufutwa) kabla ya retry, ili retry
  ianzie upya variant hiyo kutoka mwanzo (SIYO kuchanganya segments za zamani na mpya —
  hii inaweza kusababisha HLS playlist ovyo/corrupted). Variant zilizokamilika kikamilifu
  (mfano 1080p) HAZIGUSWI - zinabaki kama zilivyo (hii tayari inaonekana kufanya kazi
  kwa mujibu wa checkpoint logic iliyopo).
- Thibitisha `autoretry_for=(Exception,)` itashika `FFmpegStalledError` mpya na kufanya
  retry kiotomatiki (bila kuhitaji kuingilia kati kwa mkono kama tulivyofanya leo).
- Ongeza kikomo cha idadi ya retries maalum kwa stall (kwa mfano baada ya retries 3
  za stall, acha ku-retry na weka `processing_status = 'failed'` na ujumbe wazi wa
  sababu, ili isijirudie milele — TOFAUTI na sasa ambapo
  `max_retries=0` kwenye `convert_video_to_hls` inamaanisha hakuna retry ya kiotomatiki
  kabisa kwa sasa isipokuwa `autoretry_for` ikiwashwa - kagua hili kwa makini, kuna
  mkinzano kati ya `max_retries=0` na `autoretry_for=(Exception,)` unaohitaji ufafanuzi).

### 4. Rekebisha bug ya `bare raise` isiyo sahihi

Kwenye `convert_video_to_hls`, `except Exception as e:` block, badilisha `raise` (bila
argument) kuwa `raise e` au `raise` ikiwa tu inatokea moja kwa moja ndani ya except block
bila kupitia thread/callback nyingine katikati (hakikisha exception ya asili
haipotei kwenye `DatabaseUpdateQueue` thread boundary - kama update inafanyika kwenye
thread tofauti, exception ya thread hiyo isije "ikachanganya" na exception ya main thread).

### 5. Punguza `soft_time_limit` / `time_limit` kuendana na uhalisia

- Badilisha `soft_time_limit=14400` (masaa 4) kuwa kitu cha uhalisia zaidi kwa video za
  dakika 50-60 kwenye cores 6, mfano `soft_time_limit=5400` (dakika 90) na
  `time_limit=6300` (dakika 105) — au fanya iwe dynamic kutokana na muda wa video
  (`video.duration`) badala ya namba tuli moja inayotumika kwa video zote (fupi na ndefu).
- Hii ni "safety net" ya nje - watchdog ya #1 ndiyo itakayoshughulikia hali nyingi kabla
  ya kufika hapa, lakini soft_time_limit inabaki kama ulinzi wa mwisho.

### 6. Rekebisha `visibility_timeout` na acks_late kuepuka duplicate task delivery baada ya
   worker crash

- Chunguza uwezekano wa kuongeza `worker_cancel_long_running_tasks_on_connection_loss=True`
  kwenye Celery config (`farajayangu_be/settings/base.py`), ili endapo worker itapoteza
  uhusiano na broker/itaanguka, task za muda mrefu zisiendelee "kimya" bila ufuatiliaji.
- Fikiria kupunguza `visibility_timeout` kutoka masaa 4 kuwa kitu kinachoendana zaidi na
  `soft_time_limit` mpya (#5), ili Redis isisubiri muda mrefu mno kabla ya kutuma task
  upya endapo worker itaanguka kweli.
- Kagua lock mechanism (`video_conversion_lock_{video_id}`) — hakikisha inatumia "lock
  renewal/heartbeat" badala ya static `timeout=18000` pekee, ili lock isiendelee "kuwa
  hai" kwa task ambazo bado zinafanya kazi kwa kweli, lakini ziondolewe haraka kwa task
  zilizoachwa yatima (orphaned) na worker iliyoanguka.

### 7. (Ombi maalum la mteja) Ongeza uwezo wa "Resume/Retry" unaoweza kuchochewa kwa
   mkono kupitia admin/API endpoint

- Tengeneza endpoint au management command (mfano
  `python manage.py retry_conversion <video_id>` AU API endpoint `/api/videos/<id>/retry-conversion/`)
  inayofanya:
  1. Angalia `video.processing_checkpoint` ya sasa.
  2. Futa lock ya zamani kama ipo (`cache.delete(f"video_conversion_lock_{video_id}")`).
  3. Ita `convert_video_to_hls.delay(video_id, local_video_path=...)` upya - itaendelea
     kutoka checkpoint (variants zilizokamilika hazitarudiwa, wala assemble_chunks_task
     haitarudiwa ikiwa MP4 ya ndani bado ipo kwenye `/tmp`).
  4. Rudisha status wazi kwa mtumiaji/admin (mfano JSON: `{"status": "retry_queued",
     "resuming_from_variant": "720p"}`).
- Hii itampa admin/frontend uwezo wa "bonyeza button moja" endapo mfumo utaonyesha video
  imekwama (`processing_status == 'failed'` au `'killed'` kwa muda mrefu bila mabadiliko),
  BILA kulazimika kuanza tena kabisa (re-upload, re-assemble chunks, n.k).

## Vigezo vya mafanikio (acceptance criteria)

1. Video kubwa (GB10+, dakika50+) ikichakatwa, ikiwa ffmpeg itakwama kwa sababu yoyote
   (server load, I/O issue, n.k.), mfumo unapaswa kuigundua ndani ya dakika 5 na kujaribu
   upya kiotomatiki BILA kuhitaji uangalizi wa mkono.
2. Retry haipaswi kurudia variants zilizokamilika tayari, wala haipaswi kurudia assembly
   ya chunks kama MP4 ya ndani bado ipo.
3. Kuna njia ya wazi (log au dashboard) ya kuona: video X imekwama mara ngapi, kwa
   sababu gani, na status ya sasa.
4. Endapo retries zote (kikomo maalum) zitashindwa, video inawekwa `processing_status =
   'failed'` na ujumbe WAZI wa sababu (siyo generic "RuntimeError").
5. Endpoint/command ya "resume manually" inapatikana kwa admin kutumia bila kugusa
   database moja kwa moja.
6. `-threads` inatumia cores zote za server kiotomatiki (siyo namba tuli 4).

## Maelekezo ya ziada kwa Claude Code

- Andika unit tests kwa watchdog logic (simulate ffmpeg process isiyotuma progress kwa
  muda mrefu, thibitisha inauawa na retry inachochewa).
- Usibadilishe muundo wa jumla wa checkpoint/`processing_checkpoint` JSON field isipokuwa
  ni lazima kabisa - kuna data ya video zilizopo tayari zenye checkpoint za zamani.
- Fanya mabadiliko kwa hatua ndogo ndogo (commits tofauti kwa kila lengo hapo juu),
  siyo mabadiliko makubwa moja - hii itarahisisha kupitia code review na kurudisha nyuma
  (rollback) endapo kitu kitaharibika.
- KABLA ya deploy yoyote mpya, hakikisha `python -c "import apps.streaming.tasks.tasks"`
  (na modules zote zinazohusiana) zinapita bila ImportError - hii ilisababisha outage
  kamili ya conversion pipeline tarehe 23 Julai 2026 (masaa 1.5, task zote zilishindwa
  100%). Ongeza hii kama pre-deploy check/CI step endapo CI ipo.
