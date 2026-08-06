import os
import sys
import subprocess

def create_lnk():
    pwd = os.path.dirname(os.path.abspath(__file__))
    lnk_path = os.path.join(pwd, "Feed Workspace.lnk")
    python_exe = sys.executable
    pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
    target_path = pythonw_exe if os.path.exists(pythonw_exe) else python_exe
    
    # PowerShell script to create shortcut
    ps_script = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut('{lnk_path}')
    $Shortcut.TargetPath = '{target_path}'
    $Shortcut.Arguments = 'dashboard.py'
    $Shortcut.WorkingDirectory = '{pwd}'
    $Shortcut.Description = 'Launch Feed Workspace'
    $Shortcut.IconLocation = '{target_path},0'
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
