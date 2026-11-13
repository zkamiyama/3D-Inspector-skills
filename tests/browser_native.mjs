// Browser acceptance for the self-contained native Three.js renderer.
// Files are served from a temporary local HTTP server; external requests fail.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve, basename, join } from 'node:path';
import { chromium } from 'playwright';

const forceFallback=process.argv.includes('--disable-webgl');
const disableWebGPU=forceFallback || process.argv.includes('--disable-webgpu');
const rejectWebGPU=process.argv.includes('--reject-webgpu');
const requireWebGPU=process.argv.includes('--webgpu');
const opaque=process.argv.includes('--opaque');
const allowCDN=process.argv.includes('--allow-cdn');
const blockedFetch=process.argv.includes('--block-fetch');
const mobile=process.argv.includes('--mobile');
const files=process.argv.slice(2).filter(x=>!x.startsWith('--'));
const assets=files.length?files:[
  '.test-output/synthetic-native.html',
  '.test-output/material-native.html'
];
const output=resolve('.test-output/browser');
await mkdir(output,{recursive:true});

// Exercise the public PNG export, which captures just the model canvas.
// Alpha coverage excludes toolbar/UI pixels and catches blank GPU frames.
async function readModelFrame(page) {
  return page.evaluate(async () => {
    let uri;
    const click=HTMLAnchorElement.prototype.click;
    try {
      HTMLAnchorElement.prototype.click=function(){uri=this.href;};
      document.querySelector('#snapshot').click();
    } finally {HTMLAnchorElement.prototype.click=click;}
    const img=new Image();
    img.src=uri;
    await img.decode();
    const copy=document.createElement('canvas');
    copy.width=img.width;copy.height=img.height;
    const ctx=copy.getContext('2d');
    ctx.drawImage(img,0,0);
    const pixels=ctx.getImageData(0,0,copy.width,copy.height).data;
    let coverage=0,hash=2166136261,minX=img.width,minY=img.height,maxX=-1,maxY=-1;
    for(let i=0;i<pixels.length;i+=4){
      if(!pixels[i+3]) continue;
      coverage++;
      const pixel=i/4, x=pixel%img.width, y=Math.floor(pixel/img.width);
      minX=Math.min(minX,x); maxX=Math.max(maxX,x);
      minY=Math.min(minY,y); maxY=Math.max(maxY,y);
      hash=Math.imul(hash^i^pixels[i]^pixels[i+1]<<8^pixels[i+2]<<16,16777619);
    }
    return {coverage,hash,width:maxX-minX+1,height:maxY-minY+1};
  });
}

const backendArgs=process.env.BI_HARDWARE_GPU?['--ignore-gpu-blocklist']:
  ['--use-angle=swiftshader','--enable-unsafe-swiftshader'];
if(requireWebGPU||rejectWebGPU) {
  backendArgs.push('--enable-unsafe-webgpu');
  if(process.platform==='linux'&&!process.env.BI_HARDWARE_GPU)
    backendArgs.push('--enable-features=Vulkan','--use-vulkan=swiftshader','--disable-vulkan-surface');
}
const browser=await chromium.launch({
  headless:true,
  executablePath:process.env.BI_CHROMIUM||undefined,
  args:[...backendArgs,'--disable-gpu-sandbox']
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
    const testMode=forceFallback?'canvas':disableWebGPU?'webgl2':rejectWebGPU?'retry':requireWebGPU?'webgpu':'auto';
    const shotName=name+'.'+testMode+(mobile?'.mobile':'');
    const page=await browser.newPage({viewport:mobile?{width:390,height:840}:{width:1120,height:760},deviceScaleFactor:1});
    const issues=[],outbound=[];
    if(blockedFetch)await page.addInitScript(()=>{
      window.fetch=()=>Promise.reject(new TypeError('Failed to fetch'));
    });
    if(disableWebGPU)await page.addInitScript(()=>Object.defineProperty(navigator,'gpu',{value:undefined}));
    if(rejectWebGPU)await page.addInitScript(()=>{
      const original=HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext=function(kind,...args){
        const ctx=original.call(this,kind,...args);
        if(kind==='webgpu' && ctx) {
          // The context already owns this canvas; WebGL2 needs a new one.
          ctx.configure=()=>{window.gpuConfigurationRejected=true;throw Error('Test device configuration failure');};
        }
        return ctx;
      };
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
      if(/^https?:/.test(req.url())&&!req.url().startsWith('http://127.0.0.1:'))outbound.push(req.url());
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
      const layout=await page.evaluate(()=>{
        const rect=id=>{const r=document.querySelector(id).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right};};
        return {stage:rect('#stage'),toolbar:rect('.tools'),details:rect('.stats'),tabs:rect('.tabs'),
          aside:rect('.right-pane'),header:document.querySelectorAll('.topbar').length,
          footer:document.querySelectorAll('.footer').length,
          overflowX:document.documentElement.scrollWidth>window.innerWidth};
      });
      assert.equal(layout.header,0,'The old header must be gone');
      assert.equal(layout.footer,0,'The old footer must be gone');
      assert.ok(layout.toolbar.x>=layout.stage.x&&layout.toolbar.y>=layout.stage.y,'Floating toolbar must overlay the viewport');
      assert.ok(layout.toolbar.right<=layout.stage.right+1,'Floating toolbar must fit inside viewport');
      assert.ok(layout.tabs.height<=36,'Inspector tabs must stay compact');
      assert.ok(layout.details.height<=135,'Detail statistics must be dense');
      assert.equal(layout.overflowX,false,'No horizontal page overflow');
      if(mobile)assert.ok(layout.aside.y>=layout.stage.bottom-1,'Mobile inspector must stack below viewport');
      const status=await page.locator('#render-state').innerText();
      const problem=await page.locator('#error').innerText();
      if(forceFallback)assert.equal(status,'Canvas 2D');
      else assert.match(status,/Three\.js/,'Renderer is not native: '+status+' / '+problem+' / '+issues.join('; '));
      if(requireWebGPU)assert.equal(status,'Three.js / WebGPU');
      if(rejectWebGPU||disableWebGPU&&!forceFallback)assert.equal(status,'Three.js / WebGL2');
      if(rejectWebGPU)assert.equal(await page.evaluate(()=>window.gpuConfigurationRejected),true);
      if(allowCDN){
        assert.ok(outbound.length>0,'CDN ESM should load remote modules');
        assert.ok(outbound.every(url=>url.startsWith('https://cdn.jsdelivr.net/')),
          'CDN variant must not fetch asset data or unknown hosts: '+JSON.stringify(outbound));
      }else assert.deepEqual(outbound,[],'Viewer must make no external HTTP requests');
      const firstFrame=await readModelFrame(page);
      assert.ok(firstFrame.coverage>0,'Model PNG contains no visible pixels');
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
      if(name==='cloud') {
        assert.ok(Number(stats.vertices.replaceAll(',',''))>0,'Missing points');
        assert.equal(stats.triangles,'0');
      }
      if(name==='animated' && !forceFallback){
        const panel=page.getByRole('group',{name:'Animation playback'});
        const timeline=panel.getByRole('slider');
        await timeline.evaluate(input=>{
          input.value=String(Number(input.max)*.5);
          input.dispatchEvent(new Event('input'));
        });
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        const moved=await readModelFrame(page);
        assert.ok(moved.coverage>0);
        assert.notEqual(moved.hash,firstFrame.hash,'Seeking must change the rendered pose');
        const seekTime=await timeline.inputValue();
        await panel.getByRole('button',{name:'Play',exact:true}).click();
        await page.waitForFunction(t=>document.querySelector('.clip-controls input').value!==t,seekTime);
        await panel.getByRole('button',{name:'Pause',exact:true}).click();
      }
      await page.screenshot({path:join(output,shotName+'.png')});
      const axis = name => page.locator(`#gizmo [data-view="${name}"]`);
      const assertView = async name => {
        await page.waitForFunction(key => document.querySelector(
          `#gizmo [data-view="${key}"]`).getAttribute('aria-pressed') === 'true', name);
      };
      await axis('front').click();
      await assertView('front');
      if(name.startsWith('gaussian') && !forceFallback){
        assert.equal(state,'Gaussian splats');
        const front=await readModelFrame(page);
        assert.ok(front.height>front.width*5,'Quaternion and scale should produce a tall Gaussian');
        await page.locator('#projection').click();
        const ortho=await readModelFrame(page);
        assert.ok(Math.abs(ortho.height/front.height-1)<.06,'Ortho keeps Gaussian size at the target');
        await axis('top').click(); await assertView('top');
        const top=await readModelFrame(page);
        assert.ok(top.height<front.height/4 && Math.abs(top.width/top.height-1)<.2,
                  'Looking down the major axis should produce a smaller, round footprint');
        await page.locator('#projection').click();
        await axis('front').click(); await assertView('front');
      }
      // From an axial view the opposite dot is directly underneath.
      await axis('front').click();
      await assertView('back');
      for (const direction of ['right', 'top', 'left', 'front', 'bottom']) {
        await axis(direction).click();
        await assertView(direction);
      }
      await page.locator('[data-command="fit"]').click();
      await assertView('bottom');
      await page.locator('#projection').click();
      assert.equal(await page.locator('#projection-name').innerText(), 'Ortho');
      await page.keyboard.press('p');
      assert.equal(await page.locator('#projection-name').innerText(), 'Persp');
      const gizmo = await page.locator('#gizmo').boundingBox();
      await page.mouse.move(gizmo.x + 14, gizmo.y + 14);
      await page.mouse.down();
      await page.mouse.move(gizmo.x + 30, gizmo.y + 37, {steps: 5});
      await page.mouse.up();
      await page.waitForFunction(() => !document.querySelector('#gizmo [aria-pressed="true"]'));
      await page.locator('[data-view="iso"]').click();
      await page.locator('#details-toggle').click();
      assert.equal(await page.locator('#inspector-pane').isVisible(), false);
      await page.locator('#details-toggle').click();
      assert.equal(await page.locator('#inspector-pane').isVisible(), true);
      await page.locator('#tab-materials').click();
      assert.ok(await page.locator('.material-card').count()>0);
      await page.locator('#tab-textures').click();
      if(name==='cloud'||name==='animated'||name.startsWith('gaussian')) {
        assert.equal(await page.locator('#texture-empty').isVisible(),await page.locator('.texture-option').count()===0);
      } else {
        assert.ok(await page.locator('.texture-option').count()>0);
        await page.locator('#channel').selectOption('r');
        await page.locator('#uv-overlay').check();
      }
      await page.locator('[data-command="fit"]').click();
      await page.screenshot({path:join(output,shotName+'.textures.png')});
      assert.deepEqual(issues,[],'Browser reported a rendering error');
      console.log(JSON.stringify({asset:name,mobile,opaque,status,state,stats,layout,modelPixels:firstFrame.coverage,
        outboundCount:outbound.length,issues}));
    }finally{
      await page.close();
      await new Promise(resolve=>server.close(resolve));
    }
  }
}finally{await browser.close();}
