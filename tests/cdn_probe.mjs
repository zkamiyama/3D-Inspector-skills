import { chromium } from 'playwright';

const chromiumOptions={
  headless:true,
  executablePath:process.env.BI_CHROMIUM || undefined,
  args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--disable-gpu-sandbox']
};
const urls=[
  'https://cdn.jsdelivr.net/npm/three@0.186.0/build/three.webgpu.js',
  'https://cdn.jsdelivr.net/npm/three@0.186.0/build/three.tsl.js',
  'https://cdn.jsdelivr.net/npm/three-impostor@0.4.1/Impostor.js',
  'https://unpkg.com/three@0.186.0/build/three.webgpu.js',
  'https://esm.sh/three@0.186.0/webgpu',
];
const browser=await chromium.launch(chromiumOptions);
try{
  for(const label of ['normal','opaque-sandbox']){
    const page=await browser.newPage();
    try{
      await page.goto('about:blank');
      if(label==='opaque-sandbox'){
        await page.evaluate(()=>{
          const iframe=document.createElement('iframe');
          iframe.sandbox='allow-scripts';iframe.srcdoc='<!doctype html><title>Sandboxed</title>';
          iframe.id='probe';document.body.append(iframe);
        });
        const frame=page.frameLocator('#probe');
        await frame.locator('title').waitFor({state:'attached'});
      }
      const target=label==='opaque-sandbox' ? await (await page.locator('#probe').elementHandle()).contentFrame() : page;
      if(label==='opaque-sandbox') await target.waitForLoadState('domcontentloaded');
      const results=await target.evaluate(async urls=>{
        return await Promise.all(urls.map(async url=>{
          try{
            const response=await fetch(url,{mode:'cors',signal:AbortSignal.timeout(8000)});
            return {url,status:response.status,cors:response.headers.get('access-control-allow-origin'),type:response.headers.get('content-type')};
          }catch(error){return {url,error:error.message};}
        }));
      },urls);
      // Fetch success is not sufficient: also try an actual ESM import with
      // the same bare-specifier import map used by the upstream Box viewer.
      const map={imports:{
        'three':'https://cdn.jsdelivr.net/npm/three@0.186.0/build/three.webgpu.js',
        'three/webgpu':'https://cdn.jsdelivr.net/npm/three@0.186.0/build/three.webgpu.js',
        'three/tsl':'https://cdn.jsdelivr.net/npm/three@0.186.0/build/three.tsl.js',
        'three-impostor':'https://cdn.jsdelivr.net/npm/three-impostor@0.4.1/Impostor.js'
      }};
      await target.addScriptTag({type:'importmap',content:JSON.stringify(map)});
      const actual=await target.evaluate(async()=>{
        try {
          const pkg=await import('three-impostor');
          const three=await import('three/webgpu');
          return {success:typeof pkg.ImpostorNodeMaterial==='function',
            renderer:typeof three.WebGPURenderer};
        }catch(error){return {success:false,error:error.message};}
      });
      console.log(JSON.stringify({case:label,results,actualImport:actual}));
    }finally{await page.close();}
  }
}finally{await browser.close();}
