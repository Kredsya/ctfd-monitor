"""Run all local release contracts and preserve failures as machine-readable evidence."""
import json
import os
import platform
import subprocess
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]

class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.successful=[]
    def addSuccess(self,test):
        self.successful.append(test.id())
        super().addSuccess(test)


def main():
    output=ROOT/'test-results'; output.mkdir(exist_ok=True)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result=unittest.TextTestRunner(verbosity=2,resultclass=EvidenceResult).run(suite)
    record={
        'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'python':sys.version,
        'platform':platform.platform(),
        'tests_run':result.testsRun,
        'successful_test_ids':result.successful,
        'failures':[{'test':test.id(),'traceback':trace} for test,trace in result.failures],
        'errors':[{'test':test.id(),'traceback':trace} for test,trace in result.errors],
        'skips':[{'test':test.id(),'reason':reason} for test,reason in result.skipped],
        'expected_failures':[test.id() for test,_ in result.expectedFailures],
        'unexpected_successes':[test.id() for test in result.unexpectedSuccesses],
    }
    (output/'results.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    # A skipped requirement is not evidence of a passing release contract.
    return 0 if result.wasSuccessful() and not result.skipped and not result.expectedFailures else 1

if __name__=='__main__':
    raise SystemExit(main())
