import { readFile, writeFile } from "fs/promises";

export type M4aCoverMimeType = "image/jpeg" | "image/png";

export interface M4aCover {
  data: Uint8Array;
  mimeType: M4aCoverMimeType;
}

export interface M4aMetadata {
  title?: string;
  artist?: string;
  album?: string;
  cover?: M4aCover;
}

interface AacConfig {
  audioObjectType: number;
  sampleRate: number;
  sampleRateIndex: number;
  channelConfiguration: number;
  channelCount: number;
}

interface AacFrame {
  data: Buffer;
  duration: number;
}

const SAMPLE_RATES = [
  96_000,
  88_200,
  64_000,
  48_000,
  44_100,
  32_000,
  24_000,
  22_050,
  16_000,
  12_000,
  11_025,
  8_000,
  7_350,
] as const;

const CHANNEL_COUNTS = [0, 1, 2, 3, 4, 5, 6, 8] as const;

/**
 * ADTS AACファイルをM4Aコンテナとして保存します。
 *
 * 音声の再エンコードは行いません。入力はRadikoのようなADTS AACを想定しています。
 */
export async function writeM4aFromAdtsFiles(
  inputPaths: readonly string[],
  outputPath: string,
  metadata: M4aMetadata = {},
): Promise<void> {
  if (inputPaths.length === 0) {
    throw new Error("M4Aの入力ファイルがありません。");
  }

  const inputBuffers = await Promise.all(inputPaths.map((inputPath) => readFile(inputPath)));
  const adtsData = Buffer.concat(inputBuffers);
  const output = createM4aFromAdts(adtsData, metadata);
  await writeFile(outputPath, output);
}

/**
 * ADTS AACデータからM4Aファイルのバイト列を作成します。
 * 主にテストや、すでにメモリ上に音声データがある場合に使用します。
 */
export function createM4aFromAdts(adtsData: Uint8Array, metadata: M4aMetadata = {}): Buffer {
  const parsed = parseAdts(adtsData);
  const audioData = Buffer.concat(parsed.frames.map((frame) => frame.data));
  const ftyp = makeFtyp();
  const mdat = makeAtom("mdat", audioData);
  const dataOffset = ftyp.length + 8;
  const duration = parsed.frames.reduce((total, frame) => total + frame.duration, 0);
  const moov = makeMoov({
    config: parsed.config,
    duration,
    sampleSizes: parsed.frames.map((frame) => frame.data.length),
    dataOffset,
    metadata,
  });

  return Buffer.concat([ftyp, mdat, moov]);
}

function parseAdts(data: Uint8Array): { config: AacConfig; frames: AacFrame[] } {
  const frames: AacFrame[] = [];
  let config: AacConfig | undefined;
  let offset = 0;

  while (offset < data.length) {
    if (isPadding(data, offset)) break;

    if (hasBytes(data, offset, 3) && data[offset] === 0x49 && data[offset + 1] === 0x44 && data[offset + 2] === 0x33) {
      offset = skipId3Tag(data, offset);
      continue;
    }

    if (!hasBytes(data, offset, 7)) {
      throw new Error(`ADTSヘッダーが途中で終わっています（オフセット: ${offset}）。`);
    }

    const byte1 = data[offset + 1];
    if (data[offset] !== 0xff || (byte1 & 0xf6) !== 0xf0) {
      throw new Error(`ADTS同期語が見つかりません（オフセット: ${offset}）。`);
    }

    const byte2 = data[offset + 2];
    const byte3 = data[offset + 3];
    const protectionAbsent = (byte1 & 0x01) !== 0;
    const headerLength = protectionAbsent ? 7 : 9;
    const audioObjectType = ((byte2 >> 6) & 0x03) + 1;
    const sampleRateIndex = (byte2 >> 2) & 0x0f;
    const sampleRate = SAMPLE_RATES[sampleRateIndex];
    const channelConfiguration = ((byte2 & 0x01) << 2) | (byte3 >> 6);
    const frameLength =
      ((byte3 & 0x03) << 11) |
      (data[offset + 4] << 3) |
      ((data[offset + 5] >> 5) & 0x07);
    const rawDataBlocks = data[offset + 6] & 0x03;

    if (!sampleRate) {
      throw new Error(`未対応のAACサンプリングレートです（インデックス: ${sampleRateIndex}）。`);
    }
    if (channelConfiguration === 0) {
      throw new Error("ADTSのchannel_configuration=0（PCE）は未対応です。");
    }
    if (rawDataBlocks !== 0) {
      throw new Error("1つのADTSフレームに複数のraw_data_blockがある形式は未対応です。");
    }
    if (frameLength < headerLength) {
      throw new Error(`ADTSフレーム長が不正です（オフセット: ${offset}）。`);
    }
    if (!hasBytes(data, offset, frameLength)) {
      throw new Error(`ADTSフレームが途中で終わっています（オフセット: ${offset}）。`);
    }

    const currentConfig: AacConfig = {
      audioObjectType,
      sampleRate,
      sampleRateIndex,
      channelConfiguration,
      channelCount: CHANNEL_COUNTS[channelConfiguration],
    };

    if (!config) {
      config = currentConfig;
    } else if (
      config.audioObjectType !== currentConfig.audioObjectType ||
      config.sampleRate !== currentConfig.sampleRate ||
      config.channelConfiguration !== currentConfig.channelConfiguration
    ) {
      throw new Error("入力中のAACフレームで音声設定が変化しました。");
    }

    frames.push({
      data: Buffer.from(data.subarray(offset + headerLength, offset + frameLength)),
      // AAC-LC/HE-AACの通常のADTSフレームは1024サンプルです。
      duration: 1024,
    });
    offset += frameLength;
  }

  if (!config || frames.length === 0) {
    throw new Error("ADTS AACフレームが見つかりません。");
  }

  return { config, frames };
}

function hasBytes(data: Uint8Array, offset: number, length: number): boolean {
  return offset >= 0 && length >= 0 && offset + length <= data.length;
}

function isPadding(data: Uint8Array, offset: number): boolean {
  for (let index = offset; index < data.length; index += 1) {
    if (data[index] !== 0) return false;
  }
  return true;
}

function skipId3Tag(data: Uint8Array, offset: number): number {
  if (!hasBytes(data, offset, 10)) {
    throw new Error(`ID3タグが途中で終わっています（オフセット: ${offset}）。`);
  }

  const size =
    ((data[offset + 6] & 0x7f) << 21) |
    ((data[offset + 7] & 0x7f) << 14) |
    ((data[offset + 8] & 0x7f) << 7) |
    (data[offset + 9] & 0x7f);
  const footerLength = (data[offset + 5] & 0x10) !== 0 ? 10 : 0;
  const tagLength = 10 + size + footerLength;

  if (!hasBytes(data, offset, tagLength)) {
    throw new Error(`ID3タグが途中で終わっています（オフセット: ${offset}）。`);
  }
  return offset + tagLength;
}

function makeFtyp(): Buffer {
  return makeAtom(
    "ftyp",
    Buffer.concat([
      ascii("M4A "),
      u32(0),
      ascii("M4A "),
      ascii("mp42"),
      ascii("isom"),
    ]),
  );
}

function makeMoov(options: {
  config: AacConfig;
  duration: number;
  sampleSizes: readonly number[];
  dataOffset: number;
  metadata: M4aMetadata;
}): Buffer {
  const { config, duration, sampleSizes, dataOffset, metadata } = options;
  const metadataBox = makeMetadataBox(metadata);
  const children = [
    makeMvhd(config.sampleRate, duration),
    makeTrak(config, duration, sampleSizes, dataOffset),
  ];

  if (metadataBox) {
    children.push(makeAtom("udta", metadataBox));
  }

  return makeAtom("moov", Buffer.concat(children));
}

function makeMvhd(timescale: number, duration: number): Buffer {
  const payload = Buffer.concat([
    fullBox(),
    u32(0),
    u32(0),
    u32(timescale),
    u32(duration),
    u32(0x00010000),
    u16(0x0100),
    u16(0),
    Buffer.alloc(8),
    identityMatrix(),
    Buffer.alloc(24),
    u32(2),
  ]);
  return makeAtom("mvhd", payload);
}

function makeTrak(
  config: AacConfig,
  duration: number,
  sampleSizes: readonly number[],
  dataOffset: number,
): Buffer {
  const mdia = makeAtom(
    "mdia",
    Buffer.concat([
      makeMdhd(config.sampleRate, duration),
      makeHandler("soun", "SoundHandler"),
      makeAtom(
        "minf",
        Buffer.concat([
          makeAtom("smhd", Buffer.concat([fullBox(), u16(0), u16(0)])),
          makeDinf(),
          makeStbl(config, sampleSizes, dataOffset),
        ]),
      ),
    ]),
  );

  return makeAtom(
    "trak",
    Buffer.concat([
      makeTkhd(duration),
      mdia,
    ]),
  );
}

function makeTkhd(duration: number): Buffer {
  const payload = Buffer.concat([
    fullBox(0, 0x000007),
    u32(0),
    u32(0),
    u32(1),
    u32(0),
    u32(duration),
    Buffer.alloc(8),
    u16(0),
    u16(0),
    u16(0x0100),
    u16(0),
    identityMatrix(),
    u32(0),
    u32(0),
  ]);
  return makeAtom("tkhd", payload);
}

function makeMdhd(timescale: number, duration: number): Buffer {
  const payload = Buffer.concat([
    fullBox(),
    u32(0),
    u32(0),
    u32(timescale),
    u32(duration),
    u16(0),
    u16(0),
  ]);
  return makeAtom("mdhd", payload);
}

function makeHandler(handlerType: string, name: string): Buffer {
  const payload = Buffer.concat([
    fullBox(),
    u32(0),
    ascii(handlerType),
    Buffer.alloc(12),
    Buffer.from(`${name}\0`, "utf8"),
  ]);
  return makeAtom("hdlr", payload);
}

function makeDinf(): Buffer {
  const url = makeAtom("url ", fullBox(0, 1));
  const dref = makeAtom("dref", Buffer.concat([fullBox(), u32(1), url]));
  return makeAtom("dinf", dref);
}

function makeStbl(config: AacConfig, sampleSizes: readonly number[], dataOffset: number): Buffer {
  const stsd = makeAtom("stsd", Buffer.concat([fullBox(), u32(1), makeAudioSampleEntry(config)]));
  const stts = makeAtom("stts", Buffer.concat([fullBox(), u32(1), u32(sampleSizes.length), u32(1024)]));
  const stsc = makeAtom("stsc", Buffer.concat([fullBox(), u32(1), u32(1), u32(sampleSizes.length), u32(1)]));
  const stsz = makeAtom(
    "stsz",
    Buffer.concat([
      fullBox(),
      u32(0),
      u32(sampleSizes.length),
      ...sampleSizes.map((sampleSize) => u32(sampleSize)),
    ]),
  );
  const stco = makeAtom("stco", Buffer.concat([fullBox(), u32(1), u32(dataOffset)]));

  return makeAtom("stbl", Buffer.concat([stsd, stts, stsc, stsz, stco]));
}

function makeAudioSampleEntry(config: AacConfig): Buffer {
  const sampleEntry = Buffer.alloc(28);
  sampleEntry.writeUInt16BE(1, 6); // data_reference_index
  sampleEntry.writeUInt16BE(config.channelCount, 16);
  sampleEntry.writeUInt16BE(16, 18); // sample_size
  sampleEntry.writeUInt32BE(config.sampleRate * 0x10000, 24); // 16.16 fixed point

  return makeAtom("mp4a", Buffer.concat([sampleEntry, makeEsds(config)]));
}

function makeEsds(config: AacConfig): Buffer {
  const audioSpecificConfig = Buffer.from([
    (config.audioObjectType << 3) | (config.sampleRateIndex >> 1),
    ((config.sampleRateIndex & 1) << 7) | (config.channelConfiguration << 3),
  ]);
  const decoderSpecificInfo = descriptor(0x05, audioSpecificConfig);
  const decoderConfig = descriptor(
    0x04,
    Buffer.concat([
      Buffer.from([0x40, 0x15]), // MPEG-4 Audio / AudioStream
      u24(0), // bufferSizeDB
      u32(0), // maxBitrate
      u32(0), // avgBitrate
      decoderSpecificInfo,
    ]),
  );
  const slConfig = descriptor(0x06, Buffer.from([0x02]));
  const esDescriptor = descriptor(0x03, Buffer.concat([u16(2), Buffer.from([0]), decoderConfig, slConfig]));

  return makeAtom("esds", Buffer.concat([fullBox(), esDescriptor]));
}

function makeMetadataBox(metadata: M4aMetadata): Buffer | undefined {
  const items: Buffer[] = [];

  if (metadata.title) items.push(makeTextMetadataItem([0xa9, 0x6e, 0x61, 0x6d], metadata.title));
  if (metadata.artist) items.push(makeTextMetadataItem([0xa9, 0x41, 0x52, 0x54], metadata.artist));
  if (metadata.album) items.push(makeTextMetadataItem([0xa9, 0x61, 0x6c, 0x62], metadata.album));
  if (metadata.cover) {
    const dataType = metadata.cover.mimeType === "image/jpeg" ? 13 : 14;
    items.push(makeDataMetadataItem("covr", dataType, Buffer.from(metadata.cover.data)));
  }

  if (items.length === 0) return undefined;

  const meta = makeAtom(
    "meta",
    Buffer.concat([
      fullBox(),
      makeHandler("mdir", "MetadataHandler"),
      makeAtom("ilst", Buffer.concat(items)),
    ]),
  );
  return meta;
}

function makeTextMetadataItem(type: readonly number[], value: string): Buffer {
  return makeDataMetadataItem(type, 1, Buffer.from(value, "utf8"));
}

function makeDataMetadataItem(type: string | readonly number[], dataType: number, data: Buffer): Buffer {
  return makeAtom(
    type,
    makeAtom("data", Buffer.concat([u32(dataType), u32(0), data])),
  );
}

function descriptor(type: number, payload: Buffer): Buffer {
  return Buffer.concat([Buffer.from([type]), descriptorLength(payload.length), payload]);
}

function descriptorLength(length: number): Buffer {
  if (length < 0) throw new Error("MPEG-4 descriptorの長さが不正です。");

  const bytes: number[] = [length & 0x7f];
  let remaining = Math.floor(length / 128);
  while (remaining > 0) {
    bytes.unshift(remaining & 0x7f);
    remaining = Math.floor(remaining / 128);
  }
  for (let index = 0; index < bytes.length - 1; index += 1) {
    bytes[index] |= 0x80;
  }
  return Buffer.from(bytes);
}

function makeAtom(type: string | readonly number[], payload: Buffer): Buffer {
  const typeBytes = typeof type === "string" ? ascii(type) : Buffer.from(type);
  if (typeBytes.length !== 4) {
    throw new Error(`MP4 atomのタイプは4バイトである必要があります: ${String(type)}`);
  }

  const size = 8 + payload.length;
  if (size > 0xffffffff) {
    throw new Error("4GBを超えるM4Aは未対応です。");
  }

  return Buffer.concat([u32(size), typeBytes, payload]);
}

function identityMatrix(): Buffer {
  return Buffer.concat([
    u32(0x00010000),
    u32(0),
    u32(0),
    u32(0),
    u32(0x00010000),
    u32(0),
    u32(0),
    u32(0),
    u32(0x40000000),
  ]);
}

function fullBox(version = 0, flags = 0): Buffer {
  const result = Buffer.alloc(4);
  result.writeUInt8(version, 0);
  result.writeUIntBE(flags, 1, 3);
  return result;
}

function ascii(value: string): Buffer {
  const result = Buffer.from(value, "ascii");
  if (result.length !== 4) {
    throw new Error(`4文字のASCII文字列が必要です: ${value}`);
  }
  return result;
}

function u16(value: number): Buffer {
  const result = Buffer.alloc(2);
  result.writeUInt16BE(value);
  return result;
}

function u24(value: number): Buffer {
  const result = Buffer.alloc(3);
  result.writeUIntBE(value, 0, 3);
  return result;
}

function u32(value: number): Buffer {
  const result = Buffer.alloc(4);
  result.writeUInt32BE(value);
  return result;
}
