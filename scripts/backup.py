"""python scripts/backup.py [--verify-only BACKUP_FOLDER] [--no-restore-test]"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dreamgoods.services.backups import create_backup, verify_restore

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--verify-only", type=Path)
    p.add_argument("--no-restore-test", action="store_true")
    args = p.parse_args()
    if args.verify_only:
        verify_restore(args.verify_only)
        print("Restore and asset verification passed")
    else:
        print(create_backup(verify=not args.no_restore_test))
