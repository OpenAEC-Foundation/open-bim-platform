// The lines of an IFC file for the splitter, without their line endings, read only as far as the splitter asks for
// them. Reading ahead puts every line of the file in the queue of the stream at once: that costs memory in proportion
// to the file (the V8 heap ran out on 1.76 GB), and each line taken from a queue of millions is slow.
import { createReadStream, statSync } from "node:fs";

const CHUNK = 1024 * 1024;
/** Lines that may wait in the queue of the stream. */
const QUEUED_LINES = 1024;

/** `onPiece` sees every chunk read from the file (for tests). */
export function readLines(p, onPiece = () => {}) {
  statSync(p); // throws when the file does not exist
  const pieces = createReadStream(p, { encoding: "utf8", highWaterMark: CHUNK })[Symbol.asyncIterator]();
  let lines = [];
  let next = 0;
  let rest = "";
  let end = false;
  return new ReadableStream(
    {
      async pull(controller) {
        while (controller.desiredSize > 0) {
          if (next < lines.length) {
            controller.enqueue(lines[next++]);
          } else if (end) {
            if (rest.length) controller.enqueue(rest);
            controller.close();
            return;
          } else {
            const piece = await pieces.next();
            if (piece.done) {
              end = true;
              continue;
            }
            onPiece(piece.value);
            lines = (rest + piece.value).split(/\r?\n/);
            rest = lines.pop();
            next = 0;
          }
        }
      },
      async cancel() {
        await pieces.return?.();
      },
    },
    { highWaterMark: QUEUED_LINES },
  );
}
