# -*- coding: utf-8 -*-
"""
リハ・アシスト 音声生成エンジン (Gemini TTS ＋ Edge TTS ハイブリッド版)
- 日本語誤読（漢字・ひらがな・長音・数字）を完全に根絶したSSMLテキストを処理
- Gemini TTS (Aoede) と Edge TTS (NanamiNeural) のスマート自動ハイブリッド
- MD5キャッシュによる高速化・重複セグメント即座スキップ
- ffmpeg結合・ラウドネス正規化・タイムラインミリ秒精度同期
"""
import asyncio
import os
import sys
import re
import json
import time
import base64
import hashlib
import subprocess
import tempfile
import argparse
from pathlib import Path
import requests
import edge_tts
from dotenv import load_dotenv

# Windows UTF-8 出力対応
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

raw_keys = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]

if not API_KEYS:
    fallback_env = BASE_DIR.parent / "speech_therapy_audio" / ".env"
    if fallback_env.exists():
        load_dotenv(fallback_env, override=True)
        raw_keys = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
        API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]

SSML_DIR = BASE_DIR / "audio" / "ssml"
OUTPUT_DIR = BASE_DIR / "audio" / "output"
WEB_AUDIO_DIR = BASE_DIR / "web" / "audio"
TEMP_DIR = BASE_DIR / "temp"
CACHE_DIR = TEMP_DIR / "cache"
SILENCE_DIR = TEMP_DIR / "silence"

GEMINI_VOICE = "Aoede"
EDGE_VOICE = "ja-JP-NanamiNeural"
EDGE_RATE = "-25%"
EDGE_PITCH = "-2Hz"

CANDIDATE_MODELS = [
    "gemini-3.1-flash-tts-preview",
    "gemini-3.8-flash-lite-tts"
]

_current_key_idx = 0
_current_model_idx = 0
_gemini_quota_exhausted = False  # クォータ枯渇フラグ

def ensure_dirs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WEB_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SILENCE_DIR.mkdir(parents=True, exist_ok=True)

def parse_time_str(time_str: str) -> float:
    time_str = time_str.strip().lower()
    if time_str.endswith("ms"):
        return float(time_str[:-2]) / 1000.0
    elif time_str.endswith("s"):
        return float(time_str[:-1])
    else:
        return float(time_str)

def get_audio_duration(file_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())

def get_silence_wav(seconds: float) -> Path:
    ensure_dirs()
    silence_file = SILENCE_DIR / f"silence_{int(seconds * 1000)}ms.wav"
    if not silence_file.exists():
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi",
            "-i", "anullsrc=r=24000:cl=mono",
            "-t", str(seconds),
            "-c:a", "pcm_s16le",
            str(silence_file)
        ]
        subprocess.run(cmd, check=True)
    return silence_file

async def _synthesize_edge_tts_async(text: str, out_wav: Path):
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
        mp3_name = tmp_mp3.name
    try:
        comm = edge_tts.Communicate(text, voice=EDGE_VOICE, rate=EDGE_RATE, pitch=EDGE_PITCH)
        await comm.save(mp3_name)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", mp3_name,
            "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out_wav)
        ], check=True)
    finally:
        if os.path.exists(mp3_name):
            os.remove(mp3_name)

def synthesize_edge_tts(clean_text: str, hash_key: str) -> Path:
    """Edge TTS (NanamiNeural) による高品質・高速合成"""
    cache_wav = CACHE_DIR / f"edge_{hash_key}.wav"
    if cache_wav.exists() and cache_wav.stat().st_size > 1000:
        return cache_wav
    asyncio.run(_synthesize_edge_tts_async(clean_text, cache_wav))
    return cache_wav

def synthesize_text(clean_text: str, force_engine: str = "auto") -> Path:
    """テキスト音声合成（キャッシュ優先 ➔ Gemini TTS ➔ Edge TTSフォールバック）"""
    global _current_key_idx, _current_model_idx, _gemini_quota_exhausted
    ensure_dirs()

    if not clean_text:
        return get_silence_wav(0.1)

    hash_key = hashlib.md5(f"{clean_text}_{GEMINI_VOICE}".encode("utf-8")).hexdigest()
    gemini_cache = CACHE_DIR / f"{hash_key}.wav"
    edge_cache = CACHE_DIR / f"edge_{hash_key}.wav"

    # 1. 既存キャッシュの確認（Geminiキャッシュ最優先、次にEdgeキャッシュ）
    if gemini_cache.exists() and gemini_cache.stat().st_size > 1000:
        return gemini_cache
    if force_engine == "edge" and edge_cache.exists() and edge_cache.stat().st_size > 1000:
        return edge_cache

    # 2. 強制 Edge モードの場合
    if force_engine == "edge":
        return synthesize_edge_tts(clean_text, hash_key)

    # 3. Gemini TTS の試行（クォータが残っている場合）
    if not _gemini_quota_exhausted and API_KEYS and force_engine != "edge":
        payload = {
            "contents": [{"parts": [{"text": clean_text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": GEMINI_VOICE
                        }
                    }
                }
            }
        }

        # 3回の試行（全キー巡回）で429なら当日クォータ上限と判定してEdgeにフォールバック
        for attempt in range(len(API_KEYS)):
            api_key = API_KEYS[_current_key_idx % len(API_KEYS)]
            model_name = CANDIDATE_MODELS[_current_model_idx % len(CANDIDATE_MODELS)]
            _current_key_idx = (_current_key_idx + 1) % len(API_KEYS)

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                res = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=25)
                if res.status_code == 200:
                    part = res.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                    mime_type = part.get("mimeType", "")
                    raw_bytes = base64.b64decode(part["data"])

                    temp_bin = CACHE_DIR / f"temp_{hash_key}.bin"
                    with open(temp_bin, "wb") as f:
                        f.write(raw_bytes)

                    cmd = [
                        "ffmpeg", "-y", "-loglevel", "error",
                        "-i", str(temp_bin),
                        "-ar", "24000", "-ac", "1",
                        "-c:a", "pcm_s16le",
                        str(gemini_cache)
                    ]
                    subprocess.run(cmd, check=True)
                    if temp_bin.exists():
                        temp_bin.unlink()
                    time.sleep(1.5)
                    return gemini_cache
                elif res.status_code == 429:
                    # レート制限または日次クォータ超過
                    continue
            except Exception:
                continue

        # 全キーで429の場合は本日クォータ枯渇と判定し、以降はEdge TTSに即時フォールバック
        _gemini_quota_exhausted = True
        print(f"    [Geminiクォータ上限検知 ➔ 高品質Edge TTS (NanamiNeural) に自動切替]", flush=True)

    # 4. Edge TTS へのフォールバック
    return synthesize_edge_tts(clean_text, hash_key)

def concat_wavs_to_mp3(wav_list, out_mp3: Path):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        list_file = f.name
        for p in wav_list:
            f.write(f"file '{str(p).replace('\\', '/')}'\n")

    try:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_file,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(out_mp3)
        ]
        subprocess.run(cmd, check=True)
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)

def parse_ssml_file(xml_path: Path):
    raw_text = xml_path.read_text(encoding="utf-8")
    token_regex = re.compile(r'(<!--.*?-->|<break\s+[^>]*\/?>|<[^>]+>)', re.DOTALL)
    parts = token_regex.split(raw_text)

    tokens = []
    current_section = "開始"

    for part in parts:
        if not part:
            continue
        part_clean = part.strip()
        if not part_clean:
            continue

        if part_clean.startswith("<!--"):
            comment_content = part_clean.replace("<!--", "").replace("-->", "").strip()
            current_section = comment_content
            tokens.append({"type": "section", "section": current_section})
        elif part_clean.startswith("<break"):
            m = re.search(r'time=["\']([^"\']+)["\']', part_clean)
            if m:
                sec = parse_time_str(m.group(1))
                tokens.append({
                    "type": "silence",
                    "duration": sec,
                    "section": current_section
                })
        elif part_clean.startswith("<"):
            continue
        else:
            clean_text = " ".join(part_clean.split())
            if clean_text:
                tokens.append({
                    "type": "text",
                    "text": clean_text,
                    "section": current_section
                })

    return tokens

def process_ssml(xml_file: Path, force_engine: str = "auto"):
    print(f"\n==========================================")
    print(f"ビルド開始: {xml_file.name}")
    print(f"==========================================")

    tokens = parse_ssml_file(xml_file)
    print(f"抽出セグメント数: {len(tokens)} 件")

    stem = xml_file.stem
    if stem.startswith("breathing_"):
        out_name = "breathing"
    elif stem.startswith("arm_"):
        out_name = "arm"
    elif stem.startswith("leg_"):
        out_name = "leg"
    elif stem.startswith("voice_"):
        out_name = "voice"
    else:
        out_name = stem

    out_mp3 = OUTPUT_DIR / f"{out_name}.mp3"
    timeline_file = OUTPUT_DIR / f"{out_name}_timeline.json"

    wav_files = []
    timeline = []
    current_time = 0.0

    for i, item in enumerate(tokens):
        itype = item["type"]
        section = item.get("section", "")

        if itype == "section":
            timeline.append({
                "type": "section",
                "title": item["section"],
                "start": current_time
            })
            print(f"  [フェーズ] {item['section']}", flush=True)
        elif itype == "text":
            txt = item["text"]
            wav_path = synthesize_text(txt, force_engine=force_engine)
            dur = get_audio_duration(str(wav_path))
            wav_files.append(wav_path)

            timeline.append({
                "type": "speech",
                "text": txt,
                "section": section,
                "start": round(current_time, 2),
                "duration": round(dur, 2),
                "end": round(current_time + dur, 2)
            })
            current_time += dur
            print(f"    - 音声 ({i+1}/{len(tokens)}): {txt[:25]}... ({dur:.1f}s)", flush=True)
        elif itype == "silence":
            dur = item["duration"]
            silence_path = get_silence_wav(dur)
            wav_files.append(silence_path)

            timeline.append({
                "type": "silence",
                "section": section,
                "start": round(current_time, 2),
                "duration": round(dur, 2),
                "end": round(current_time + dur, 2)
            })
            current_time += dur
            print(f"    - 待機/無音: {dur:.1f}s", flush=True)

    print(f"\n{len(wav_files)} 個のオーディオパーツを結合 & ラウドネス正規化中: {out_mp3.name}...", flush=True)
    concat_wavs_to_mp3(wav_files, out_mp3)

    total_dur = get_audio_duration(str(out_mp3))
    print(f"完了! 総再生時間: {total_dur:.1f}秒 ({total_dur/60:.2f}分)", flush=True)

    WEB_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    web_mp3 = WEB_AUDIO_DIR / f"{out_name}.mp3"
    web_timeline = WEB_AUDIO_DIR / f"{out_name}_timeline.json"

    timeline_data = {
        "title": xml_file.name,
        "total_duration": round(total_dur, 2),
        "voice": "Gemini TTS (Aoede) / Edge Neural (Nanami)",
        "timeline": timeline
    }
    with open(timeline_file, "w", encoding="utf-8") as f:
        json.dump(timeline_data, f, ensure_ascii=False, indent=2)

    with open(web_timeline, "w", encoding="utf-8") as f:
        json.dump(timeline_data, f, ensure_ascii=False, indent=2)

    import shutil
    shutil.copy2(out_mp3, web_mp3)

    return out_mp3, total_dur

def update_web_config_and_cache():
    """
    全トラックの実測再生時間から rehab_config.json と sw.js のキャッシュバージョンを自動同期・修正する
    """
    config_file = BASE_DIR / "web" / "rehab_config.json"
    sw_file = BASE_DIR / "web" / "sw.js"
    if not config_file.exists():
        return

    with open(config_file, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    # 1. 各トラックの実測値反映
    for track_id, track_info in config_data.get("tracks", {}).items():
        mp3_path = WEB_AUDIO_DIR / f"{track_id}.mp3"
        if mp3_path.exists():
            dur = get_audio_duration(str(mp3_path))
            sec = int(round(dur))
            track_info["duration"] = sec
            m = sec // 60
            s = sec % 60
            if s >= 45:
                track_info["durationLabel"] = f"約{m + 1}分"
            elif s >= 15:
                track_info["durationLabel"] = f"約{m}分半"
            else:
                track_info["durationLabel"] = f"約{m}分"

    # 2. 各コースの合計時間自動計算
    for course in config_data.get("courses", []):
        total_sec = sum(config_data["tracks"][t_id]["duration"] for t_id in course.get("tracks", []) if t_id in config_data.get("tracks", {}))
        m = total_sec // 60
        s = total_sec % 60
        if s >= 45:
            course["timeLabel"] = f"約{m + 1}分"
        elif s >= 15:
            course["timeLabel"] = f"約{m}分半"
        else:
            course["timeLabel"] = f"約{m}分"

    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)
    print("  ==> [Webアプリ自動同期完了] web/rehab_config.json (トラック・コース所要時間)", flush=True)

    # 3. sw.js のキャッシュバージョン自動更新
    if sw_file.exists():
        sw_code = sw_file.read_text(encoding="utf-8")
        m = re.search(r"CACHE_NAME = 'rehab-voice-app-v(\d+)';", sw_code)
        if m:
            cur_ver = int(m.group(1))
            new_ver = cur_ver + 1
            new_code = re.sub(r"CACHE_NAME = 'rehab-voice-app-v\d+';", f"CACHE_NAME = 'rehab-voice-app-v{new_ver}';", sw_code)
            sw_file.write_text(new_code, encoding="utf-8")
            print(f"  ==> [Webアプリ自動同期完了] web/sw.js (キャッシュバージョン v{cur_ver} -> v{new_ver})", flush=True)

def main():
    ensure_dirs()
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", default="", help="対象トラック名 (voice, leg, arm, breathing)")
    parser.add_argument("--engine", default="auto", choices=["auto", "gemini", "edge"], help="使用エンジン")
    args = parser.parse_args()

    files = sorted(list(SSML_DIR.glob("*.xml")))
    if args.target:
        files = [f for f in files if args.target.lower() in f.stem.lower()]

    print(f"対象SSMLファイル: {len(files)} 件 (エンジン: {args.engine})", flush=True)

    results = []
    for f in files:
        mp3_path, dur = process_ssml(f, force_engine=args.engine)
        results.append((f.name, mp3_path.name, dur))

    print("\n==========================================", flush=True)
    print("全音声の生成・Web反映が完了しました！", flush=True)
    print("==========================================", flush=True)
    for orig, mp3, dur in results:
        print(f" - {orig} -> {mp3} ({dur:.1f}秒 / {dur/60:.2f}分)", flush=True)

    # Webアプリ側の設定・キャッシュを完全自動同期
    update_web_config_and_cache()

if __name__ == "__main__":
    main()
