#!/usr/bin/env python3
"""
YouTube OAuth TV API Helper
Отримання довгоживучого токену через youtube.com/activate
"""

import json
import time
import requests
from pathlib import Path

# OAuth credentials для YouTube TV API (публічні)
CLIENT_ID = "861556708454-d6dlm3lh05idd8npek18k6be8ba3oc68.apps.googleusercontent.com"
CLIENT_SECRET = "SboVhoG9s0rNafixCSGGKXAT"
SCOPES = "http://gdata.youtube.com https://www.googleapis.com/auth/youtube"

TOKEN_FILE = Path("/tmp/youtube_oauth_token.json")


def get_device_code():
    """Крок 1: Отримати device code для активації"""
    url = "https://oauth2.googleapis.com/device/code"
    data = {
        "client_id": CLIENT_ID,
        "scope": SCOPES,
    }
    
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()


def poll_for_token(device_code, interval=5):
    """Крок 2: Чекаємо поки користувач активує код"""
    url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    
    while True:
        response = requests.post(url, data=data)
        result = response.json()
        
        if "access_token" in result:
            return result
        
        if result.get("error") == "authorization_pending":
            print(f"⏳ Чекаємо активації... (перевірка кожні {interval}с)")
            time.sleep(interval)
        elif result.get("error") == "slow_down":
            interval += 5
            time.sleep(interval)
        else:
            raise Exception(f"OAuth error: {result}")


def refresh_token(refresh_token):
    """Оновити access token використовуючи refresh token"""
    url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()


def save_token(token_data):
    """Зберегти токен у файл"""
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
    print(f"✅ Token saved to {TOKEN_FILE}")


def load_token():
    """Завантажити токен з файлу"""
    if not TOKEN_FILE.exists():
        return None
    
    return json.loads(TOKEN_FILE.read_text())


def get_valid_token():
    """Отримати валідний access token (оновлює якщо потрібно)"""
    token_data = load_token()
    
    if not token_data:
        raise Exception("No token found. Run oauth setup first.")
    
    # Якщо токен скоро закінчиться - оновлюємо
    if "refresh_token" in token_data:
        print("🔄 Refreshing access token...")
        new_token = refresh_token(token_data["refresh_token"])
        
        # Зберігаємо refresh_token з попереднього
        new_token["refresh_token"] = token_data["refresh_token"]
        save_token(new_token)
        
        return new_token["access_token"]
    
    return token_data.get("access_token")


def setup_oauth():
    """Інтерактивна настройка OAuth"""
    print("🔐 YouTube OAuth TV API Setup")
    print("=" * 50)
    
    # Крок 1: Отримати код
    device_info = get_device_code()
    
    user_code = device_info["user_code"]
    verification_url = device_info["verification_url"]
    
    print(f"\n📱 Відкрийте у браузері: {verification_url}")
    print(f"🔑 Введіть код: {user_code}")
    print("\n⏳ Чекаю активації...")
    
    # Крок 2: Чекаємо токен
    token_data = poll_for_token(
        device_info["device_code"],
        device_info.get("interval", 5)
    )
    
    # Зберігаємо
    save_token(token_data)
    
    print("\n✅ OAuth setup completed!")
    print(f"📝 Access token: {token_data['access_token'][:20]}...")
    print(f"🔄 Refresh token: {token_data['refresh_token'][:20]}...")
    print(f"⏰ Expires in: {token_data.get('expires_in', 'N/A')}s")
    
    return token_data


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup_oauth()
    elif len(sys.argv) > 1 and sys.argv[1] == "refresh":
        token = get_valid_token()
        print(f"✅ Valid token: {token[:20]}...")
    else:
        print("Usage:")
        print("  python oauth_helper.py setup    # Initial setup")
        print("  python oauth_helper.py refresh  # Get/refresh token")
