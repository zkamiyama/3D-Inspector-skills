// The decoder and .wasm are unmodified copies from Three.js 0.186.0's
// examples/jsm/libs/basis (Binomial, Apache 2.0). Run only during HTML export.
const fs = require('node:fs');
const path = require('node:path');
const init = require('./transcoder.cjs');

async function main() {
  const [input, output] = process.argv.slice(2);
  const module = await init({ wasmBinary: fs.readFileSync(path.join(__dirname, 'transcoder.wasm')) });
  module.initializeBasis();
  const file = new module.KTX2File(fs.readFileSync(input));
  try {
    if (!file.isValid() || file.isHDR() || !(file.isUASTC() || file.isETC1S()) ||
        file.getFaces() !== 1 || file.getLayers() > 1 || file.isVideo())
      throw Error('Expected a two-dimensional ETC1S or UASTC LDR material texture');
    const width = file.getWidth(), height = file.getHeight();
    const bytes = width * height * 4;
    const RGBA32 = 13;
    if (!width || !height || bytes > 512 * 1024 * 1024 ||
        file.getImageTranscodedSizeInBytes(0, 0, 0, RGBA32) !== bytes)
      throw Error('Invalid or oversized RGBA texture');
    const rgba = new Uint8Array(bytes);
    if (!file.startTranscoding() || !file.transcodeImage(rgba, 0, 0, 0, RGBA32, 0, -1, -1))
      throw Error('Invalid Basis payload');
    // ETC1S Red/Green uses the alpha slice for its second spatial channel.
    if (file.isETC1S() && file.getDFDTotalSamples() === 2 && file.getDFDChannelID1() === 4) {
      for (let i=0; i<rgba.length; i+=4) {rgba[i+1]=rgba[i+3]; rgba[i+3]=255;}
    }
    fs.writeFileSync(output, rgba);
  } finally {
    file.close();
    file.delete();
  }
}
main().catch(error => { console.error(error.message); process.exitCode=1; });
