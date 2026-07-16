import os
import sys
import subprocess

def create_lnk():
    pwd = os.path.dirname(os.path.abspath(__file__))
    lnk_path = os.path.join(pwd, "Feed Workspace.lnk")
    
    # PowerShell script to create shortcut
    ps_script = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut('{lnk_path}')
    $Shortcut.TargetPath = 'pythonw.exe'
    $Shortcut.Arguments = 'dashboard.py'
    $Shortcut.WorkingDirectory = '{pwd}'
    $Shortcut.Description = 'Launch Feed Workspace'
    $Shortcut.Save()
    """
    
    print(f"Creating shortcut at: {lnk_path}...")
    result = subprocess.run(["powershell", "-Command", ps_script], capture_output=True, text=True)
    if result.returncode == 0:
        print("Shortcut created successfully!")
    else:
        print(f"Error creating shortcut: {result.stderr}")

if __name__ == "__main__":
    create_lnk()
