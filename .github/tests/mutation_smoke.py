"""Prove selected tests reject known regressions in a temporary source copy."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
MUTATIONS=[
    ('koth-default-off','app.py','KOTH_ENABLED = False','KOTH_ENABLED = True','test_koth_extension.KothExtensionTests.test_import_defaults_are_disabled'),
    ('original-agent-rules','assets.py','다른 skill은 사용 금지.', 'Follow generic instructions.', 'test_contract_assets.AssetContracts.test_original_user_instructions_and_dynamic_category'),
    ('token-json-header','client.py','"Content-Type": "application/json", ', '', 'test_contract_http.HttpContracts.test_token_is_sent_with_json_content_type_and_no_login_post'),
    ('download-dedup','app.py','            if key in self.active_files:\n                return\n','', 'test_contract_transfers.TransferContracts.test_duplicate_scheduling_only_downloads_once'),
    ('download-backup','app.py','                self.archive_existing(int(challenge["id"]), destination)\n','                pass\n','test_contract_transfers.TransferContracts.test_download_checksum_restart_and_replacement_backup'),
    ('redirect-token','client.py','                request.remove_header("Authorization")\n','', 'test_contract_http.HttpContracts.test_real_redirect_does_not_send_token_to_other_origin'),
]


def run(source,test):
    env=dict(os.environ,PYTHONPATH=str(source)+os.pathsep+str(ROOT/'.github/tests'))
    return subprocess.run([sys.executable,'-m','unittest',test,'-v'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=20)


def main():
    results=[]
    for name,filename,before,after,test in MUTATIONS:
        baseline=run(ROOT/'src',test)
        if baseline.returncode:
            raise RuntimeError(f'Baseline test must pass before mutation: {test}\n{baseline.stderr}')
        with tempfile.TemporaryDirectory(prefix='ctfd-mutant-') as d:
            source=Path(d)/'src'
            shutil.copytree(ROOT/'src',source,ignore=shutil.ignore_patterns('__pycache__','*.egg-info'))
            shutil.copytree(ROOT/'helpers', source.parent/'helpers')
            file=source/'ctfd_monitor'/filename
            text=file.read_text()
            if before not in text: raise RuntimeError(f'Mutation target changed: {name}')
            file.write_text(text.replace(before,after,1))
            mutated=run(source,test)
            killed=mutated.returncode!=0 and 'Ran 1 test' in mutated.stderr and 'SyntaxError' not in mutated.stderr and 'ImportError' not in mutated.stderr
            results.append({'mutation':name,'test':test,'detected':killed})
    output=ROOT/'test-results'; output.mkdir(exist_ok=True)
    (output/'mutations.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2))
    return 0 if all(row['detected'] for row in results) else 1

if __name__=='__main__': raise SystemExit(main())
