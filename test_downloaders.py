from downloaders import YouTubeDownloader, InstagramDownloader

# Test URL detection
youtube = YouTubeDownloader()
instagram = InstagramDownloader()

test_urls = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://www.instagram.com/p/ABC123/",
    "https://www.instagram.com/reel/XYZ789/",
    "https://www.facebook.com/video",
]

print("🧪 Testing URL detection:\n")
for url in test_urls:
    yt_match = youtube.can_handle(url)
    ig_match = instagram.can_handle(url)
    
    platform = "YouTube" if yt_match else ("Instagram" if ig_match else "Unknown")
    emoji = "✅" if (yt_match or ig_match) else "❌"
    
    print(f"{emoji} {url[:50]:50s} → {platform}")
