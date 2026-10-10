"""Stride-aware replacement for the pinned ColorOS SDK's YUV copier.

The software APS encoder consumes a full-size NV21 frame. OEM ApsUtils
copies plane 2 verbatim, which only works when that plane already holds VU.
Ranchu also supplies planar I420 and interleaved UV. Read each component
using its own row/pixel strides without changing the Image's buffers.
"""
import struct


def patch_yuv_copier(dex):
    # Method/type IDs belong to the SHA-256-checked SDK in build_coloros.py.
    offset, capacity = 0x26acec, 188
    if struct.unpack_from('<HHHH', dex, offset) != (11, 3, 4, 0):
        raise RuntimeError('Unexpected ApsUtils YUV method header')
    if dex[offset + 16:offset + 24] != bytes.fromhex('3808 b300 6e10 5601'):
        raise RuntimeError('Unexpected ApsUtils YUV method body')
    words, labels, branches = [], {}, []

    def emit(*values):
        words.extend(values)

    def label(name):
        labels[name] = len(words)

    def branch(opcode, a, b, target):
        branches.append((len(words), target))
        emit(opcode | (a << 8) | (b << 12), 0)

    def jump(target):
        branches.append((len(words), target))
        emit(0x29, 0)  # goto/16

    def const(register, value):
        emit(0x13 | register << 8, value)  # const/16

    def call(method, registers, result, object_result=False):
        packed = sum(reg << (4 * i) for i, reg in enumerate(registers))
        emit(0x6e | len(registers) << 12, method, packed)
        emit((0x0c if object_result else 0x0a) | result << 8)

    # v13 = Image, v14 = output format, v15 = reusable byte[].
    # v0/1 = plane dimensions, v2 = planes, v3 = plane index,
    # v4/5 = output offset/step, v6 = buffer, v7/8 = row/pixel strides,
    # v9/10 = row/column, v11 = source offset, v12 = temporary.
    branch(0x38, 13, 0, 'invalid')  # if-eqz Image
    call(0x0156, [13], 12)  # Image.getFormat
    const(11, 35)
    branch(0x33, 12, 11, 'invalid')
    call(0x015b, [13], 0)  # Image.getWidth
    call(0x0158, [13], 1)  # Image.getHeight
    emit(0x92 | 12 << 8, 0 | 1 << 8)  # mul-int v12,v0,v1
    emit(0xda | 12 << 8, 12 | 3 << 8)  # mul-int/lit8 v12,v12,3
    emit(0xdb | 12 << 8, 12 | 2 << 8)  # div-int/lit8 v12,v12,2
    branch(0x38, 15, 0, 'allocate')
    emit(0x21 | 11 << 8 | 15 << 12)  # array-length v11,v15
    branch(0x35, 11, 12, 'planes')
    label('allocate')
    emit(0x23 | 15 << 8 | 12 << 12, 0x0fc5)  # new-array byte[]
    label('planes')
    call(0x0159, [13], 2, True)  # Image.getPlanes
    const(3, 0)
    label('plane')
    const(12, 3)
    branch(0x35, 3, 12, 'done')
    const(12, 1)
    branch(0x33, 3, 12, 'dimensions')
    emit(0xe1 | 0 << 8, 0 | 1 << 8)  # shr-int/lit8 width,1
    emit(0xe1 | 1 << 8, 1 | 1 << 8)  # shr-int/lit8 height,1
    label('dimensions')
    emit(0x46 | 4 << 8, 2 | 3 << 8)  # aget-object plane
    call(0x0153, [4], 7)  # Plane.getRowStride
    call(0x0152, [4], 8)  # Plane.getPixelStride
    call(0x0151, [4], 6, True)  # Plane.getBuffer
    const(4, 0)
    const(5, 1)
    branch(0x38, 3, 0, 'rows')
    const(5, 2)
    emit(0x92 | 4 << 8, 0 | 1 << 8)  # chroma width * height
    emit(0xda | 4 << 8, 4 | 4 << 8)  # full Y size
    const(12, 17)
    branch(0x33, 14, 12, 'nv12')
    const(12, 1)  # NV21: U starts at Ysize+1, V at Ysize
    branch(0x33, 3, 12, 'rows')
    jump('odd')
    label('nv12')
    const(12, 2)  # NV12: V starts at Ysize+1, U at Ysize
    branch(0x33, 3, 12, 'rows')
    label('odd')
    emit(0xd8 | 4 << 8, 4 | 1 << 8)
    label('rows')
    const(9, 0)
    label('row')
    branch(0x35, 9, 1, 'next_plane')
    emit(0x92 | 11 << 8, 9 | 7 << 8)  # source = row * rowStride
    const(10, 0)
    label('column')
    branch(0x35, 10, 0, 'next_row')
    call(0x8e21, [6, 11], 12)  # ByteBuffer.get(int)
    emit(0x4f | 12 << 8, 15 | 4 << 8)  # aput-byte
    emit(0xb0 | 4 << 8 | 5 << 12)  # out += step
    emit(0xb0 | 11 << 8 | 8 << 12)  # source += pixelStride
    emit(0xd8 | 10 << 8, 10 | 1 << 8)
    jump('column')
    label('next_row')
    emit(0xd8 | 9 << 8, 9 | 1 << 8)
    jump('row')
    label('next_plane')
    emit(0xd8 | 3 << 8, 3 | 1 << 8)
    jump('plane')
    label('done')
    emit(0x11 | 15 << 8)  # return-object
    label('invalid')
    const(15, 0)
    emit(0x11 | 15 << 8)
    for start, target in branches:
        words[start + 1] = (labels[target] - start) & 0xffff
    if len(words) > capacity:
        raise RuntimeError('YUV copier exceeds the pinned DEX code slot')
    words.extend([0] * (capacity - len(words)))
    struct.pack_into('<HHHHII', dex, offset, 16, 3, 2, 0, 0, capacity)
    struct.pack_into('<' + 'H' * capacity, dex, offset + 16, *words)
