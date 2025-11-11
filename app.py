from flask import Flask, render_template, Response, request, jsonify
import time
from leer_y_validar_patente import SmartPark

app = Flask(__name__)

# Single SmartPark instance shared by all routes
sp = SmartPark()

@app.route('/')
def index():
    """Serve main page"""
    return render_template('index.html')

def gen_frames():
    """Generate MJPEG frames for video streaming"""
    while True:
        try:
            frame = sp.get_frame_jpeg()
            if not frame:
                time.sleep(0.05)  # tiny wait if no frame
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.033)  # ~30fps
        except GeneratorExit:
            break
        except Exception:
            time.sleep(0.1)  # error cooldown

@app.route('/video_feed')
def video_feed():
    """Stream MJPEG video"""
    return Response(gen_frames(),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start', methods=['POST'])
def start_recognition():
    """Start plate recognition"""
    sp.start()
    return jsonify({"status": "ok", "message": "Reconocimiento iniciado"})

@app.route('/stop', methods=['POST'])
def stop_recognition():
    """Stop plate recognition"""
    sp.stop()
    return jsonify({"status": "ok", "message": "Reconocimiento detenido"})

@app.route('/status')
def get_status():
    """Get system status"""
    return jsonify(sp.get_status())

@app.route('/logs')
def get_logs():
    """Get recent logs"""
    return jsonify(sp.get_logs())

@app.route('/manual', methods=['POST'])
def manual_entry():
    """Process manual plate entry"""
    data = request.get_json()
    if not data or 'patente' not in data:
        return jsonify({
            "status": "error",
            "message": "Patente requerida"
        }), 400
    
    result = sp.manual_patente(data['patente'])
    return jsonify(result)

if __name__ == '__main__':
    # Run Flask development server
    app.run(host='0.0.0.0', port=5000, debug=True)
