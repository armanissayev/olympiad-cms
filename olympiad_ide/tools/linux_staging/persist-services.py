from pathlib import Path
import subprocess
for name in ['postgres','log','resource','judge','runtime','worker','ranking','ingress']:
 directory=Path('/etc/systemd/system/multi-user.target.wants');directory.mkdir(exist_ok=True);link=directory/('cms-ide-stage-'+name+'.service')
 if not link.exists():link.symlink_to('/etc/systemd/system/'+link.name)
subprocess.run(['systemctl','daemon-reload'],check=True)
for name in ['postgres','log','resource','judge','runtime','worker','ranking','ingress']:
 subprocess.run(['systemctl','is-active','cms-ide-stage-'+name],check=True)
 subprocess.run(['systemctl','is-enabled','cms-ide-stage-'+name],check=True)
