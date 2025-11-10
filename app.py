from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
import os
import sqlite3
from werkzeug.utils import secure_filename
import requests
import random

app = Flask(__name__)
app.secret_key = 'kisanbandhu-2025-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# API Keys
WEATHER_API_KEY = 'your_openweather_api_key_here'
TWILIO_ACCOUNT_SID = 'your_twilio_account_sid'
TWILIO_AUTH_TOKEN = 'your_twilio_auth_token'


# Database setup
def init_db():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect('kisanbandhu.db')
    c = conn.cursor()

    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        location TEXT DEFAULT 'India',
        language TEXT DEFAULT 'en',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Chat history table
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT NOT NULL,
        response TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Pest analysis history
    c.execute('''CREATE TABLE IF NOT EXISTS analysis_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        image_path TEXT,
        disease_name TEXT,
        confidence REAL,
        treatment TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Soil analysis history
    c.execute('''CREATE TABLE IF NOT EXISTS soil_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        crop_type TEXT,
        location TEXT,
        recommendation TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Weather alerts
    c.execute('''CREATE TABLE IF NOT EXISTS weather_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        location TEXT,
        message TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    conn.commit()
    conn.close()

def get_db():
    """Get database connection with row factory"""
    conn = sqlite3.connect('kisanbandhu.db')
    conn.row_factory = sqlite3.Row
    return conn


# Initialize database
init_db()


# Authentication decorator
def login_required(f):
    """Decorator to require login for routes"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session and 'guest_user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


# Main routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone', '').strip()
        name = request.form.get('name', '').strip()
        location = request.form.get('location', 'India').strip()
        language = request.form.get('language', 'en')

        if not phone:
            return render_template('login.html', error='Phone number is required')

        conn = get_db()

        if name:  # Registration
            if conn.execute('SELECT id FROM users WHERE phone = ?', (phone,)).fetchone():
                return render_template('login.html',
                                       error='Phone number already registered! Please login instead.',
                                       show_register=True)

            conn.execute('INSERT INTO users (name, phone, location, language) VALUES (?, ?, ?, ?)',
                         (name, phone, location, language))
            conn.commit()

        # Login
        user = conn.execute('SELECT * FROM users WHERE phone = ?', (phone,)).fetchone()
        conn.close()

        if not user:
            return render_template('login.html',
                                   error='Phone number not found! Please register first.',
                                   show_login=True)

        # Set session
        session.update({
            'user_id': user['id'],
            'user_name': user['name'],
            'user_phone': user['phone'],
            'user_language': user['language'],
            'user_location': user['location']
        })

        return redirect(url_for('dashboard'))

    return render_template('login.html')


@app.route('/guest_login', methods=['GET', 'POST'])
def guest_login():
    if request.method == 'POST':
        session['guest_user'] = True
        return redirect(url_for('dashboard'))

    return render_template('guest_login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()

    # Get recent activities
    recent_data = {
        'chats': conn.execute('SELECT * FROM chat_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5',
                              (session.get('user_id', None),)).fetchall(),
        'analyses': conn.execute('SELECT * FROM analysis_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5',
                                 (session.get('user_id', None),)).fetchall(),
        'soil': conn.execute('SELECT * FROM soil_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 3',
                             (session.get('user_id', None),)).fetchall(),
        'alerts': conn.execute('SELECT * FROM weather_alerts WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5',
                               (session.get('user_id', None),)).fetchall()
    }
    conn.close()

    return render_template('dashboard.html', user_name=session.get('user_name', 'Guest'), **recent_data)


# AI Chat feature
@app.route('/chat')
@login_required
def chat():
    return render_template('chat.html', user_name=session.get('user_name', 'Guest'))

@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    data = request.get_json() or {}
    message = data.get('message', '').strip()

    if not message:
        return jsonify({'error': 'Message cannot be empty'}), 400

    # Generate AI response
    response = generate_ai_response(message, session.get('user_language', 'en'))

    # Save to database
    if 'user_id' in session:
        conn = get_db()
        conn.execute('INSERT INTO chat_history (user_id, message, response) VALUES (?, ?, ?)',
                     (session['user_id'], message, response))
        conn.commit()
        conn.close()

    return jsonify({'response': response})

def generate_ai_response(message, language='en'):
    """Generate AI response based on message intent"""
    message_lower = message.lower()

    responses = {
        'greeting': {
            'en': 'Hello! I am KisanBandhu, your AI farm assistant. How can I help you today?',
            'hi': 'नमस्ते! मैं किसानबंधु हूं, आपका AI कृषि सहायक। आज मैं आपकी कैसे मदद कर सकता हूं?',
            'pa': 'ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਮੈਂ ਕਿਸਾਨਬੰਧੂ ਹਾਂ, ਤੁਹਾਡਾ AI ਖੇਤੀ ਸਹਾਇਕ।'
        },
        'weather': {
            'en': 'Check the Weather section for real-time forecasts and SMS alerts!',
            'hi': 'मौसम जानने के लिए Weather सेक्शन में जाएं।',
            'pa': 'ਮੌਸਮ ਦੀ ਜਾਂਚ ਕਰਨ ਲਈ Weather ਸੈਕਸ਼ਨ ਵਿੱਚ ਜਾਓ।'
        },
        'pest': {
            'en': 'I can identify pests! Go to Analyze section and upload a photo.',
            'hi': 'मैं कीटों की पहचान कर सकता हूं! Analyze सेक्शन में फोटो अपलोड करें।',
            'pa': 'ਮੈਂ ਕੀੜਿਆਂ ਦੀ ਪਛਾਣ ਕਰ ਸਕਦਾ ਹਾਂ! Analyze ਸੈਕਸ਼ਨ ਵਿੱਚ ਫੋਟੋ ਅੱਪਲੋਡ ਕਰੋ।'
        },
        'soil': {
            'en': 'Visit Soil Analysis section for NPK recommendations!',
            'hi': 'NPK सिफारिशों के लिए Soil Analysis सेक्शन देखें!',
            'pa': 'NPK ਸਿਫ਼ਾਰਸ਼ਾਂ ਲਈ Soil Analysis ਸੈਕਸ਼ਨ ਵੇਖੋ!'
        },
        'default': {
            'en': 'I help with weather alerts, pest detection, soil analysis, and crop advice. What would you like to know?',
            'hi': 'मैं मौसम अलर्ट, कीट पहचान, मिट्टी विश्लेषण में मदद करता हूं। क्या जानना चाहेंगे?',
            'pa': 'ਮੈਂ ਮੌਸਮ, ਕੀੜੇ, ਮਿੱਟੀ ਵਿਸ਼ਲੇਸ਼ਣ ਵਿੱਚ ਮਦਦ ਕਰਦਾ ਹਾਂ।'
        }
    }

    # Intent detection
    intent_keywords = {
        'greeting': ['hello', 'hi', 'hey', 'namaste', 'नमस्ते', 'ਸਤ ਸ੍ਰੀ ਅਕਾਲ'],
        'weather': ['weather', 'rain', 'temperature', 'mausam', 'मौसम', 'ਮੌਸਮ'],
        'pest': ['pest', 'insect', 'disease', 'keeda', 'rog', 'कीड़ा', 'बीमारी', 'ਕੀੜਾ'],
        'soil': ['soil', 'mitti', 'npk', 'मिट्टी', 'ਮਿੱਟੀ', 'fertilizer', 'खाद', 'ਖਾਦ']
    }

    for intent, keywords in intent_keywords.items():
        if any(word in message_lower for word in keywords):
            return responses[intent].get(language, responses[intent]['en'])

    return responses['default'].get(language, responses['default']['en'])


# Weather feature
@app.route('/weather')
@login_required
def weather():
    return render_template('weather.html',
                           user_name=session.get('user_name', 'Guest'),
                           user_location=session.get('user_location', 'Delhi'))

@app.route('/api/weather', methods=['POST'])
@login_required
def api_weather():
    data = request.get_json() or {}
    location = data.get('location', session.get('user_location', 'Delhi'))

    try:
        url = f'http://api.openweathermap.org/data/2.5/weather?q={location}&appid={WEATHER_API_KEY}&units=metric'
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            return jsonify({'error': 'Location not found'}), 404

        weather_data = response.json()
        temp = weather_data['main']['temp']
        description = weather_data['weather'][0]['description']

        # Log weather alerts for extreme conditions
        if 'rain' in description.lower() or temp > 40 or temp < 5:
            if 'user_id' in session:
                conn = get_db()
                alert_message = f"Weather Alert: {description}, Temp: {temp}°C in {location}"
                conn.execute('INSERT INTO weather_alerts (user_id, location, message) VALUES (?, ?, ?)',
                             (session['user_id'], location, alert_message))
                conn.commit()
                conn.close()

        return jsonify({
            'temperature': temp,
            'humidity': weather_data['main']['humidity'],
            'description': description,
            'wind_speed': weather_data['wind']['speed'],
            'icon': weather_data['weather'][0]['icon'],
            'feels_like': weather_data['main']['feels_like'],
            'pressure': weather_data['main']['pressure']
        })

    except requests.exceptions.RequestException:
        return jsonify({'error': 'Weather service unavailable'}), 503
    except KeyError:
        return jsonify({'error': 'Invalid weather data received'}), 500


# Pest detection feature
@app.route('/analyze')
@login_required
def analyze():
    return render_template('analyze.html', user_name=session.get('user_name', 'Guest'))

@app.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400

    file = request.files['image']
    if not file or file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Save uploaded image
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{timestamp}_{filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        file.save(filepath)
    except Exception:
        return jsonify({'error': 'Failed to save image'}), 500

    # Mock AI analysis
    disease_name, confidence, treatment = mock_pest_analysis()

    # Save to database
    if 'user_id' in session:
        conn = get_db()
        conn.execute(
            'INSERT INTO analysis_history (user_id, image_path, disease_name, confidence, treatment) VALUES (?, ?, ?, ?, ?)',
            (session['user_id'], filepath, disease_name, confidence, treatment))
        conn.commit()
        conn.close()

    return jsonify({
        'disease_name': disease_name,
        'confidence': confidence,
        'treatment': treatment,
        'image_url': '/' + filepath
    })


def mock_pest_analysis():
    """Mock AI pest detection - replace with real ML model"""
    diseases = [
        ('Wheat Leaf Rust', 'Apply Propiconazole fungicide @ 0.1%. Remove infected leaves.'),
        ('Aphid Infestation', 'Spray neem oil solution (5ml/liter). Use yellow sticky traps.'),
        ('Powdery Mildew', 'Apply sulfur-based fungicide. Improve air circulation.'),
        ('Bacterial Blight', 'Use Copper Oxychloride @ 3g/liter. Remove infected leaves.'),
        ('Healthy Plant', 'Plant looks healthy! Continue regular care.')
    ]

    disease, treatment = random.choice(diseases)
    confidence = round(random.uniform(0.85, 0.98), 2)
    return disease, confidence, treatment


# Soil analysis feature
@app.route('/soil')
@login_required
def soil():
    return render_template('soil.html',
                           user_name=session.get('user_name', 'Guest'),
                           user_location=session.get('user_location', ''))

@app.route('/api/soil_analysis', methods=['POST'])
@login_required
def api_soil_analysis():
    data = request.get_json() or {}
    crop_type = data.get('crop', 'Wheat')
    location = data.get('location', session.get('user_location', 'Punjab'))

    # Get soil recommendations
    soil_data = get_soil_recommendations(crop_type, location)

    # Save to database
    if 'user_id' in session:
        conn = get_db()
        conn.execute('INSERT INTO soil_history (user_id, crop_type, location, recommendation) VALUES (?, ?, ?, ?)',
                     (session['user_id'], crop_type, location, soil_data['recommendation']))
        conn.commit()
        conn.close()

    return jsonify(soil_data)


def get_soil_recommendations(crop_type, location):
    """Get crop-specific soil and fertilizer recommendations"""
    recommendations = {
        'Wheat': {
            'nitrogen': 'High (120-150 kg/ha)',
            'phosphorus': 'Medium (60-80 kg/ha)',
            'potassium': 'Medium (40-60 kg/ha)',
            'ph': '6.0-7.5 (Optimal)',
            'recommendation': f'For {crop_type} in {location}: Apply Urea @ 130 kg/ha + DAP @ 100 kg/ha + MOP @ 50 kg/ha. Split nitrogen: 50% at sowing, 25% at first irrigation, 25% at second irrigation.'
        },
        'Rice': {
            'nitrogen': 'Very High (150-180 kg/ha)',
            'phosphorus': 'Medium (60-80 kg/ha)',
            'potassium': 'High (60-80 kg/ha)',
            'ph': '5.5-7.0 (Optimal)',
            'recommendation': f'For {crop_type} in {location}: Apply Urea @ 180 kg/ha + DAP @ 100 kg/ha + MOP @ 70 kg/ha. Split nitrogen: 50% at transplanting, 25% at tillering, 25% at panicle initiation.'
        },
        'Cotton': {
            'nitrogen': 'High (120-140 kg/ha)',
            'phosphorus': 'High (80-100 kg/ha)',
            'potassium': 'High (60-80 kg/ha)',
            'ph': '6.0-8.0 (Optimal)',
            'recommendation': f'For {crop_type} in {location}: Apply Urea @ 140 kg/ha + DAP @ 120 kg/ha + MOP @ 80 kg/ha. Add organic manure @ 5-10 tons/ha.'
        },
        'Maize': {
            'nitrogen': 'High (120-150 kg/ha)',
            'phosphorus': 'High (60-80 kg/ha)',
            'potassium': 'Medium (40-60 kg/ha)',
            'ph': '5.8-7.0 (Optimal)',
            'recommendation': f'For {crop_type} in {location}: Apply Urea @ 150 kg/ha + DAP @ 100 kg/ha + MOP @ 60 kg/ha. Split nitrogen in 3 parts.'
        }
    }

    result = recommendations.get(crop_type, recommendations['Wheat'])

    # Add location-specific note
    if any(region in location for region in ['Punjab', 'Haryana']):
        result['note'] = 'Your region has alkaline soils - monitor pH regularly.'
    else:
        result['note'] = 'Get soil tested at nearest Krishi Vigyan Kendra (KVK).'

    return result


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
