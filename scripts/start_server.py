import http.server
import socketserver
import webbrowser
import socket
import os
from pathlib import Path

PORT = 8080
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

def run():
    os.chdir(WEB_DIR)
    local_ip = get_local_ip()
    local_url = f"http://localhost:{PORT}/index.html"
    mobile_url = f"http://{local_ip}:{PORT}/index.html"

    print("==================================================")
    print(" リハ・アシスト Webアプリ サーバー起動中")
    print("--------------------------------------------------")
    print(f" [PCから開く]     : {local_url}")
    print(f" [同じWi-Fiのスマホから開く]: {mobile_url}")
    print("==================================================")
    print(" 終了するには Ctrl + C を押してください。\n")

    # ブラウザを開く
    webbrowser.open(local_url)

    # 0.0.0.0にバインドしてLAN内のスマホからも接続可能にする
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nサーバーを停止しました。")

if __name__ == "__main__":
    run()
