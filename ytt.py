import yt_dlp

# Function to choose the download options based on user input
def get_download_options():
    print("Select the format you want to download:")
    print("1. MP3 (Audio Only)")
    print("2. MP4 (Video)")
    format_choice = input("Enter 1 for MP3 or 2 for MP4: ")

    print("Select the quality:")
    print("1. High Quality")
    print("2. Low Quality")
    quality_choice = input("Enter 1 for High Quality or 2 for Low Quality: ")

    if format_choice == '1':
        if quality_choice == '1':
            return {
                'format': 'bestaudio/best',  # Best audio quality
                'outtmpl': '%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',  # High quality MP3
                }],
            }
        else:
            return {
                'format': 'bestaudio/best',  # Best audio quality
                'outtmpl': '%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',  # Low quality MP3
                }],
            }

    elif format_choice == '2':
        if quality_choice == '1':
            return {
                'format': 'bestvideo+bestaudio/best',  # Best video and audio
                'outtmpl': '%(title)s.%(ext)s',
            }
        else:
            return {
                'format': 'worstvideo+worstaudio/worst',  # Worst video and audio
                'outtmpl': '%(title)s.%(ext)s',
            }
    else:
        print("Invalid selection, please try again.")
        return get_download_options()

# Function to download the video/audio
def download_video(url, ydl_opts):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

if __name__ == '__main__':
    video_url = input("Enter the YouTube video URL: ")
    download_options = get_download_options()  # Get user-selected download options
    download_video(video_url, download_options)  # Download with selected options
    print("Download completed!")
