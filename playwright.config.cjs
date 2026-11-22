const {defineConfig}=require('@playwright/test');
module.exports=defineConfig({
  testDir:'./tests/browser',
  use:{baseURL:'http://127.0.0.1:8765',browserName:'chromium'},
  webServer:{command:`${process.env.PYTHON || '.venv/bin/python'} -m uvicorn app.main:app --host 127.0.0.1 --port 8765`,url:'http://127.0.0.1:8765/api/health',reuseExistingServer:false,env:{PAPER_MODELAR_DATA_DIR:require('node:fs').mkdtempSync(require('node:path').join(require('node:os').tmpdir(),'paper-modelar-e2e-'))}},
});
