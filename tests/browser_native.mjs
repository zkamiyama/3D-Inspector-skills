// Browser acceptance for the self-contained native Three.js renderer.
// Files are served from a temporary local HTTP server; external requests fail.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve, dirname, basename, join } from 'node:path';
import { chromium } from 'playwright';

const forceFallback=process.argv.includes('--disable-webgl');
const opaque=process.argv.includes('--opaque');
const allowCDN=process.argv.includes('--allow-cdn');
const blockedFetch=process.argv.includes('--block-fetch');
const files=process.argv.slice(2).filter(x=>!x.startsWith('--'));
const assets=files.length?files:[
  '.test-output/synthetic-native.html',
  '.test-output/material-native.html'
];
const output=resolve('.test-output/browser');
await mkdir(output,{recursive:true});
const browser=await chromium.launch({
  headless:true,
  executablePath:process.env.BI_CHROMIUM||undefined,
  args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--disable-gpu-sandbox']
});
try{
  for(const asset of assets){
    const path=resolve(asset);
    const html=await readFile(path);
    const server=createServer((req,res)=>{
      if(req.url==='/favicon.ico'){res.writeHead(204);res.end();return;}
      if(req.url==='/'){
        res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Content-Length':html.byteLength});
        res.end(html);return;
      }
      res.writeHead(404);res.end('not found');
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const port=server.address().port;
    const name=basename(asset).replace(/\.html$/,'');
    const page=await browser.newPage({viewport:{width:1120,height:760},deviceScaleFactor:1});
    const issues=[],outbound=[];
    if(blockedFetch)await page.addInitScript(()=>{
      window.fetch=()=>Promise.reject(new TypeError('Failed to fetch'));
    });
    if(forceFallback)await page.addInitScript(()=>{
      const orig=HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext=function(kind,...args){
        if(kind==='webgl2'||kind==='webgl'||kind==='experimental-webgl')return null;
        return orig.call(this,kind,...args);
      };
    });
    page.on('pageerror',err=>issues.push('PAGE: '+err.message));
    page.on('console',msg=>{if(msg.type()==='error') issues.push('CONSOLE: '+msg.text());});
    page.on('request',req=>{
      if(!req.url().startsWith('http://127.0.0.1:'))outbound.push(req.url());
    });
    try{
      if(opaque){
        await page.goto('about:blank');
        await page.setContent(html.toString('utf8'),{waitUntil:'domcontentloaded'});
      }else await page.goto('http://127.0.0.1:'+port+'/',{waitUntil:'domcontentloaded'});
      await page.waitForFunction(()=>{
        const status=document.querySelector('#render-state')?.textContent||'';
        return status.includes('Three.js')||status.includes('Canvas 2D')||
          document.querySelector('#error')?.classList.contains('visible');
      },null,{timeout:90000});
      const status=await page.locator('#render-state').innerText();
      const problem=await page.locator('#error').innerText();
      if(forceFallback)assert.equal(status,'Canvas 2D');
      else assert.match(status,/Three\.js/,'Renderer is not native: '+status+' / '+problem+' / '+issues.join('; '));
      if(allowCDN){
        assert.ok(outbound.length>0,'CDN ESM should load remote modules');
        assert.ok(outbound.every(url=>url.startsWith('https://cdn.jsdelivr.net/')),
          'CDN variant must not fetch asset data or unknown hosts: '+JSON.stringify(outbound));
      }else assert.deepEqual(outbound,[],'Viewer must make no external HTTP requests');
      await page.waitForTimeout(1200);
      const state=await page.locator('#stage-state').innerText();
      const stats=await page.evaluate(()=>{
        const value=id=>document.querySelector('#stat-'+id).textContent;
        return {vertices:value('vertices'),triangles:value('triangles'),
          meshes:value('meshes'),materials:value('materials')};
      });
      if(name.includes('synthetic') && !forceFallback){
        assert.equal(state,'Native Box');
        assert.deepEqual(stats,{vertices:'24',triangles:'12',meshes:'1',materials:'1'});
      }
      await page.screenshot({path:join(output,name+'.png')});
      await page.locator('[data-view="front"]').click();
      await page.locator('#projection').click();
      await page.locator('#tab-materials').click();
      assert.ok(await page.locator('.material-card').count()>0);
      await page.locator('#tab-textures').click();
      assert.ok(await page.locator('.texture-option').count()>0);
      await page.locator('#channel').selectOption('r');
      await page.locator('#uv-overlay').check();
      await page.locator('[data-command="fit"]').click();
      await page.screenshot({path:join(output,name+'.textures.png')});
      console.log(JSON.stringify({asset:name,opaque,status,state,stats,
        outboundCount:outbound.length,issues}));
    }finally{
      await page.close();
      await new Promise(resolve=>server.close(resolve));
    }
  }
}finally{await browser.close();}
