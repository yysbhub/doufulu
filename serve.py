from waitress import serve
from app import app  # 假设你的 Flask 应用实例在 app.py 文件中

if __name__ == "__main__":
    serve(app, host='0.0.0.0', port=80)
