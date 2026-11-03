"""Build only: keep EDB manifests and opt bundled command-line programs into UTF-8.

Windows 10 1903+ activeCodePage fixes ANSI argv/filesystem paths without changing
Windows locale, moving user data or requiring administrator privileges at runtime.
"""
import hashlib
from pathlib import Path
import sys
from xml.dom import minidom
from PyInstaller.utils.win32 import winmanifest

root = Path(sys.argv[1])
ASM = 'urn:schemas-microsoft-com:asm.v3'
SMI = 'http://schemas.microsoft.com/SMI/2019/WindowsSettings'
for exe in sorted((root / 'bin').glob('*.exe')):
    try:
        xml = winmanifest.read_manifest_from_executable(str(exe))
        if isinstance(xml, tuple): xml = xml[1]
    except ValueError:
        xml = winmanifest.create_application_manifest()
    dom = minidom.parseString(xml)
    applications = dom.getElementsByTagNameNS(ASM, 'application')
    if applications:
        application = applications[0]
    else:
        application = dom.createElementNS(ASM, 'asmv3:application')
        application.setAttribute('xmlns:asmv3', ASM)
        dom.documentElement.appendChild(application)
    settings = application.getElementsByTagNameNS(ASM, 'windowsSettings')
    if settings:
        settings = settings[0]
    else:
        settings = dom.createElementNS(ASM, 'asmv3:windowsSettings')
        settings.setAttribute('xmlns:asmv3', ASM)
        application.appendChild(settings)
    for old in list(settings.getElementsByTagNameNS(SMI, 'activeCodePage')):
        old.parentNode.removeChild(old)
    cp = dom.createElementNS(SMI, 'activeCodePage')
    cp.setAttribute('xmlns', SMI)
    cp.appendChild(dom.createTextNode('UTF-8'))
    settings.appendChild(cp)
    winmanifest.write_manifest_to_executable(str(exe), dom.toxml(encoding='UTF-8'))
    print('UTF-8 manifest:', exe.name)
(root / 'doc' / 'bundled-sha256.txt').write_text(hashlib.sha256((root / 'bin' / 'postgres.exe').read_bytes()).hexdigest() + '\n')
