import asyncio
import os
import re
import sys
import json
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import edge_tts

VOICE = "ja-JP-NanamiNeural"  # 落ち着いた高品質な日本語音声
DEFAULT_RATE = "-15%"
DEFAULT_PITCH = "-2Hz"

BASE_DIR = Path(__file__).resolve().parent.parent
SSML_DIR = BASE_DIR / "audio" / "ssml"
OUTPUT_DIR = BASE_DIR / "audio" / "output"
WEB_AUDIO_DIR = BASE_DIR / "web" / "audio"

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
        file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())

async def synthesize_text_wav(text: str, out_wav: str, voice: str, rate: str, pitch: str):
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
        mp3_name = tmp_mp3.name
    try:
        comm = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
        await comm.save(mp3_name)
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", mp3_name,
            "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le",
            out_wav
        ], check=True)
    finally:
        if os.path.exists(mp3_name):
            os.remove(mp3_name)

def make_silence_wav(duration_sec: float, out_wav: str):
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
        "-t", str(duration_sec),
        "-c:a", "pcm_s16le",
        out_wav
    ], check=True)

def concat_wavs_to_mp3(wav_list, out_mp3: str):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        list_file = f.name
        for p in wav_list:
            f.write(f"file '{p.replace('\\', '/')}'\n")

    try:
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_file,
            "-c:a", "libmp3lame", "-b:a", "128k",
            out_mp3
        ], check=True)
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)

def parse_ssml_file(xml_path: Path):
    """
    SSMLファイルをトークン（セクション・テキスト・break）に順序通りパースする
    """
    raw_text = xml_path.read_text(encoding="utf-8")

    # rate/pitch設定
    rate = DEFAULT_RATE
    pitch = DEFAULT_PITCH
    prosody_match = re.search(r'<prosody\s+([^>]+)>', raw_text)
    if prosody_match:
        attrs = prosody_match.group(1)
        r_m = re.search(r'rate=["\']([^"\']+)["\']', attrs)
        p_m = re.search(r'pitch=["\']([^"\']+)["\']', attrs)
        if r_m:
            r_val = r_m.group(1)
            # 85% -> -15%
            if r_val.endswith("%") and not r_val.startswith(("+", "-")):
                pct = int(r_val[:-1]) - 100
                rate = f"{pct:+d}%"
            else:
                rate = r_val
        if p_m:
            # -2st -> -2Hz 近似またはそのまま
            pitch = p_m.group(1).replace("st", "Hz")

    # タグとコメントのトークン化
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
            # コメント（セクション名）
            comment_content = part_clean.replace("<!--", "").replace("-->", "").strip()
            current_section = comment_content
            tokens.append({"type": "section", "section": current_section})
        elif part_clean.startswith("<break"):
            # breakタグ
            m = re.search(r'time=["\']([^"\']+)["\']', part_clean)
            if m:
                sec = parse_time_str(m.group(1))
                tokens.append({
                    "type": "silence",
                    "duration": sec,
                    "section": current_section
                })
        elif part_clean.startswith("<"):
            # speak, prosody 等のラッパータグはスキップ
            continue
        else:
            # 音声テキスト
            # 句読点等で分割されたテキスト
            clean_text = " ".join(part_clean.split())
            if clean_text:
                tokens.append({
                    "type": "text",
                    "text": clean_text,
                    "section": current_section
                })

    return tokens, rate, pitch

async def process_ssml(xml_file: Path):
    print(f"\n==========================================")
    print(f"Processing: {xml_file.name}")
    print(f"==========================================")

    tokens, rate, pitch = parse_ssml_file(xml_file)
    print(f"Extracted {len(tokens)} items (Rate: {rate}, Pitch: {pitch})")

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

    with tempfile.TemporaryDirectory() as tmpdir:
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
                print(f"  [フェーズ] {item['section']}")
            elif itype == "text":
                wav_path = os.path.join(tmpdir, f"segment_{i:04d}.wav")
                await synthesize_text_wav(item["text"], wav_path, VOICE, rate, pitch)
                dur = get_audio_duration(wav_path)
                wav_files.append(wav_path)

                timeline.append({
                    "type": "speech",
                    "text": item["text"],
                    "section": section,
                    "start": round(current_time, 2),
                    "duration": round(dur, 2),
                    "end": round(current_time + dur, 2)
                })
                current_time += dur
                print(f"    - 音声: {item['text'][:30]}... ({dur:.1f}s)")
            elif itype == "silence":
                dur = item["duration"]
                wav_path = os.path.join(tmpdir, f"segment_{i:04d}.wav")
                make_silence_wav(dur, wav_path)
                wav_files.append(wav_path)

                timeline.append({
                    "type": "silence",
                    "section": section,
                    "start": round(current_time, 2),
                    "duration": round(dur, 2),
                    "end": round(current_time + dur, 2)
                })
                current_time += dur
                print(f"    - 無音/待機: {dur:.1f}s")

        print(f"\nConcatenating {len(wav_files)} audio chunks into {out_mp3}...")
        concat_wavs_to_mp3(wav_files, str(out_mp3))

        total_dur = get_audio_duration(str(out_mp3))
        print(f"Done! Total Audio Length: {total_dur:.1f}s ({total_dur/60:.2f} min)")

        # Web側にもコピー
        WEB_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        web_mp3 = WEB_AUDIO_DIR / f"{out_name}.mp3"
        web_timeline = WEB_AUDIO_DIR / f"{out_name}_timeline.json"

        # JSON書き出し
        timeline_data = {
            "title": xml_file.name,
            "total_duration": round(total_dur, 2),
            "voice": VOICE,
            "timeline": timeline
        }
        with open(timeline_file, "w", encoding="utf-8") as f:
            json.dump(timeline_data, f, ensure_ascii=False, indent=2)

        with open(web_timeline, "w", encoding="utf-8") as f:
            json.dump(timeline_data, f, ensure_ascii=False, indent=2)

        # MP3コピー
        import shutil
        shutil.copy2(out_mp3, web_mp3)

    return out_mp3, total_dur

async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WEB_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(list(SSML_DIR.glob("*.xml")))
    if len(sys.argv) > 1:
        target = sys.argv[1].lower()
        files = [f for f in files if target in f.stem.lower()]
    print(f"Found {len(files)} SSML files to generate.")

    results = []
    for f in files:
        mp3_path, dur = await process_ssml(f)
        results.append((f.name, mp3_path.name, dur))

    print("\n==========================================")
    print("ALL AUDIO GENERATION COMPLETED SUCCESSFULLY!")
    print("==========================================")
    for orig, mp3, dur in results:
        print(f" - {orig} -> {mp3} ({dur:.1f}s / {dur/60:.2f}分)")

if __name__ == "__main__":
    asyncio.run(main())
