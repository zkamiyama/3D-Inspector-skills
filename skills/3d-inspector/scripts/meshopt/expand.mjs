// Convert bounded source-buffer slices using the local upstream decoder.
import { open, readFile } from 'node:fs/promises';
import { MeshoptDecoder } from './decoder.mjs';

const [jobsPath, compressedPath, outputPath] = process.argv.slice(2);
const jobs = JSON.parse(await readFile(jobsPath, 'utf8'));
await MeshoptDecoder.ready;
const source = await open(compressedPath);
const destination = await open(outputPath, 'wx');
try {
  for (const {offset, length, mode, count, stride, filter} of jobs) {
    const packed = Buffer.alloc(length);
    let consumed = 0;
    while (consumed < length) {
      const { bytesRead } = await source.read(packed, consumed, length-consumed, offset+consumed);
      if (!bytesRead) throw new Error('Truncated meshopt input');
      consumed += bytesRead;
    }
    const result = Buffer.alloc(count * stride);
    MeshoptDecoder.decodeGltfBuffer(result, count, stride, packed, mode, filter);
    await destination.writeFile(result);
  }
} finally {
  await source.close();
  await destination.close();
}
