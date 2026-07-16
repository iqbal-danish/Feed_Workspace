import os
from ftplib import FTP
import paramiko

class FTPClient:
    """Core transfer agent handling standard FTP and secure SFTP file uploads."""

    @staticmethod
    def upload_ftp(host: str, port: int, username: str, password: str, 
                   remote_dir: str, remote_filename: str, local_filepath: str) -> None:
        """Uploads a local file to a remote FTP server."""
        if not os.path.exists(local_filepath):
            raise FileNotFoundError(f"Local file not found: {local_filepath}")
            
        port = int(port) if port else 21
        ftp = FTP()
        
        # Connect & Login
        ftp.connect(host, port, timeout=30)
        ftp.login(username, password)
        
        # Navigate to directory (create folders recursively if they don't exist)
        if remote_dir:
            parts = [p for p in remote_dir.split('/') if p]
            # Handle absolute path starting position
            if remote_dir.startswith('/'):
                ftp.cwd('/')
            for part in parts:
                try:
                    ftp.cwd(part)
                except Exception:
                    # Directory doesn't exist, create and cd into it
                    ftp.mkd(part)
                    ftp.cwd(part)
                    
        # Upload file in binary mode
        with open(local_filepath, 'rb') as f:
            ftp.storbinary(f"STOR {remote_filename}", f)
            
        ftp.quit()

    @staticmethod
    def upload_sftp(host: str, port: int, username: str, password: str, 
                    remote_dir: str, remote_filename: str, local_filepath: str) -> None:
        """Uploads a local file to a remote SFTP server using SSH/paramiko."""
        if not os.path.exists(local_filepath):
            raise FileNotFoundError(f"Local file not found: {local_filepath}")
            
        port = int(port) if port else 22
        
        # Setup SSH Client
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Connect
        ssh.connect(host, port=port, username=username, password=password, timeout=30)
        
        # Open SFTP channel
        sftp = ssh.open_sftp()
        
        # Navigate & create directory if needed
        if remote_dir:
            parts = [p for p in remote_dir.split('/') if p]
            current_path = ""
            if remote_dir.startswith('/'):
                current_path = "/"
            
            for part in parts:
                # Ensure correct forward slash paths on the remote server
                if current_path and not current_path.endswith('/'):
                    current_path += "/"
                current_path += part
                
                try:
                    sftp.chdir(current_path)
                except IOError:
                    # Create directory if it does not exist
                    sftp.mkdir(current_path)
                    sftp.chdir(current_path)
                    
        # Upload file
        sftp.put(local_filepath, remote_filename)
        
        # Clean up
        sftp.close()
        ssh.close()
