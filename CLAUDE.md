# リハ・アシスト（rehab-voice-app）開発・保守ガイドライン

お母様（ALS療養中・ベッドサイド）に向けた、音声主導の自立支援・リハビリWebアプリケーションの保守・改修規約です。

---

## 1. 音声生成とWebアプリ自動同期の絶対ルール（自動化原則）

**「音声を変更した際は、Webアプリ側も完全に自動で同期・修正・デプロイすること」**

1. **音声再生成コマンド**:
   ```bash
   python scripts/generate_audio.py
   ```
   - このスクリプトを実行すると、以下の処理が**すべて自動で実行**されます：
     - VOICEPEAKから高品位音声（48kHz WAV/192kbps MP3）の生成・ラウドネス正規化（-16 LUFS）
     - `timeline.json` のミリ秒精度での再構築
     - `web/audio/` への MP3 および `timeline.json` の自動コピー
     - `web/rehab_config.json` の各トラック・コースの所要時間（`durationLabel`, `timeLabel`）の自動再計算・更新
     - `web/sw.js` のキャッシュバージョン（`CACHE_NAME = 'rehab-voice-app-vX'`）の自動インクリメント
2. **コミット＆GitHub Pages 自動デプロイ**:
   - 音声やWebアプリの修正完了後は、必ず `git add`, `git commit`, `git push origin main` を行い、GitHub Pages への自動デプロイまで完遂すること。
3. **日本語テキストの自然さ・優しさ原則**:
   - 機械的な「息を吸って。」「やさしく、「あー」。」等のぶつ切りを排し、お母様に寄り添う温かい語りかけ文にする。
   - VOICEPEAKは標準的な漢字表記・仮名遣いで極めて高精度なイントネーションを自律生成するため、不自然な平仮名崩しや長音記号は避ける。

---

## 2. 音声合成エンジンの構成
- **VOICEPEAK（最優先・既定エンジン）**:
  - エンジンパス: `C:\Program Files\VOICEPEAK\voicepeak.exe`
  - ボイス: `Japanese Female 1`（落ち着き・温かみ・包容力のある女性アナウンサー声）または `Japanese Female 2`（明るく爽やかで優しい女性声）
  - 話速: `95`（落ち着いたゆったりペース）
  - 感情: `happy=25`（温かく微笑んでいるようなトーン）
  - ローカル実行のためAPI制限・通信途絶なし・48kHzスタジオ品質。
- **Edge Neural TTS (ja-JP-NanamiNeural)**:
  - VOICEPEAK非存在環境での自動フォールバック。

---

## 3. Webアプリ起動・検証
- バッチファイル: `アプリ起動.bat`（ダブルクリックでサーバー起動＆ブラウザ自動オープン）
- 手動起動: `python scripts/start_server.py`（ポート 8080）
- ローカルアクセス: `http://localhost:8080/index.html`
