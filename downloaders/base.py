"""Base downloader class"""

import re
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger("ytbot")


class BaseDownloader(ABC):
    """Base class for all downloaders"""
    
    @staticmethod
    @abstractmethod
    def can_handle(url: str) -> bool:
        """Check if this downloader can handle the URL"""
        pass
    
    @abstractmethod
    async def download(
        self, 
        url: str, 
        download_dir: Path,
        progress_callback=None
    ) -> Tuple[Path, str]:
        """
        Download media from URL
        
        Returns:
            Tuple[Path, str]: (filepath, media_type)
            media_type: 'audio', 'video', 'photo', 'carousel'
        """
        pass
    
    @staticmethod
    def clean_filename(filename: str) -> str:
        """Clean filename from special characters"""
        clean = filename.replace("%20", "_")
        clean = re.sub(r'%[0-9A-Fa-f]{2}', '_', clean)
        clean = re.sub(r'[^\w\s._-]', '_', clean)
        clean = re.sub(r'_+', '_', clean)
        return clean.strip('_')
