"""
Cleanup script to remove media files from server.
All media should be stored in Cloudflare R2, not on the server.

Run this after fixing the bug to clean up old files.
"""
import os
import shutil
from pathlib import Path

# Path to media directory
MEDIA_DIR = Path(__file__).parent / 'media'

def cleanup_media_directory():
    """Remove all files from media directory."""
    if not MEDIA_DIR.exists():
        print("✓ No media directory found - nothing to clean")
        return
    
    print(f"Cleaning up: {MEDIA_DIR}")
    
    # Count files before deletion
    file_count = sum(1 for _ in MEDIA_DIR.rglob('*') if _.is_file())
    
    if file_count == 0:
        print("✓ Media directory is already empty")
        return
    
    print(f"Found {file_count} files to delete")
    
    # Confirm deletion
    response = input(f"\n⚠️  Delete {file_count} files from {MEDIA_DIR}? (yes/no): ")
    
    if response.lower() != 'yes':
        print("❌ Cleanup cancelled")
        return
    
    # Delete all files and subdirectories
    try:
        for item in MEDIA_DIR.iterdir():
            if item.is_file():
                item.unlink()
                print(f"  Deleted file: {item.name}")
            elif item.is_dir():
                shutil.rmtree(item)
                print(f"  Deleted directory: {item.name}")
        
        print(f"\n✅ Successfully deleted {file_count} files")
        print("✅ All media files should now be in Cloudflare R2 only")
        
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")

if __name__ == '__main__':
    print("=" * 60)
    print("Media Directory Cleanup Script")
    print("=" * 60)
    print("\nThis script removes all files from the media/ directory.")
    print("All media files should be stored in Cloudflare R2, not locally.")
    print()
    
    cleanup_media_directory()
