"""File cleanup utilities"""

import logging
from pathlib import Path
from datetime import datetime, timedelta

log = logging.getLogger("ytbot")


def cleanup_old_files(download_dir: Path, max_age_minutes: int = 30, active_downloads: set = None):
    """Видаляє файли старіші за max_age_minutes, крім активних завантажень"""
    if not download_dir.exists():
        return
    
    if active_downloads is None:
        active_downloads = set()
    
    now = datetime.now()
    cutoff = now - timedelta(minutes=max_age_minutes)
    
    cleaned = 0
    for file in download_dir.iterdir():
        if not file.is_file():
            continue
            
        # Не чіпаємо активні завантаження
        if str(file) in active_downloads:
            continue
        
        # Перевіряємо час модифікації
        mtime = datetime.fromtimestamp(file.stat().st_mtime)
        if mtime < cutoff:
            try:
                file.unlink()
                cleaned += 1
                log.info(f"🧹 Cleaned old file: {file.name}")
            except Exception as e:
                log.warning(f"Failed to clean {file.name}: {e}")
    
    if cleaned > 0:
        log.info(f"🧹 Cleaned {cleaned} old files")


def cleanup_all_except_active(download_dir: Path, active_downloads: set = None):
    """Видаляє всі файли крім активних завантажень"""
    if not download_dir.exists():
        return
    
    if active_downloads is None:
        active_downloads = set()
    
    cleaned = 0
    for file in download_dir.iterdir():
        if not file.is_file():
            continue
            
        # Не чіпаємо активні завантаження
        if str(file) in active_downloads:
            continue
        
        try:
            file.unlink()
            cleaned += 1
            log.info(f"🧹 Cleaned: {file.name}")
        except Exception as e:
            log.warning(f"Failed to clean {file.name}: {e}")
    
    if cleaned > 0:
        log.info(f"🧹 Cleaned {cleaned} files")
