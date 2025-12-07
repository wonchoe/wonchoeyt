"""Upload utilities for large files"""

import logging
from pathlib import Path
import aiohttp

log = logging.getLogger("ytbot")


async def upload_to_gofile(filepath: Path) -> str:
    """
    Upload file to gofile.io (more reliable than file.io)
    
    Args:
        filepath: Path to file to upload
    
    Returns:
        str: Download URL
    """
    async with aiohttp.ClientSession() as session:
        # Get server
        async with session.get('https://api.gofile.io/servers') as resp:
            data = await resp.json()
            server = data['data']['servers'][0]['name']
        
        # Upload file
        with open(filepath, 'rb') as f:
            form = aiohttp.FormData()
            form.add_field('file', f, filename=filepath.name)
            
            async with session.post(f'https://{server}.gofile.io/contents/uploadfile', data=form) as resp:
                result = await resp.json()
                if result['status'] != 'ok':
                    raise Exception(f"Upload failed: {result}")
                
                return result['data']['downloadPage']
