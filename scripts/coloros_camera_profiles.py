"""Camcorder profiles for the virtual front/rear cameras, up to 1080p30."""
import copy
import xml.etree.ElementTree as ET
import struct


def _varint(data: bytes, offset: int):
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError('protobuf varint is too long')
    raise ValueError('truncated protobuf varint')


def _encode_varint(value: int) -> bytes:
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7f) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def disable_portrait_mode(protobuf: bytes) -> bytes:
    """Remove nested mode records that advertise the unavailable portrait ISP."""
    target = b'portrait_mode'

    def rewrite(data: bytes) -> bytes:
        output = bytearray()
        offset = 0
        try:
            while offset < len(data):
                field_start = offset
                key, offset = _varint(data, offset)
                wire = key & 7
                if wire == 0:
                    _, offset = _varint(data, offset)
                    output.extend(data[field_start:offset])
                elif wire == 1:
                    offset += 8
                    output.extend(data[field_start:offset])
                elif wire == 2:
                    size, payload_start = _varint(data, offset)
                    payload_end = payload_start + size
                    if payload_end > len(data):
                        raise ValueError('truncated protobuf payload')
                    payload = data[payload_start:payload_end]
                    nested = rewrite(payload)
                    if target in payload and target in nested:
                        # This is either the mode record itself or a direct
                        # string field. Both must disappear from the mode map.
                        continue_offset = payload_end
                        offset = continue_offset
                        continue
                    output.extend(data[field_start:offset])
                    output.extend(_encode_varint(len(nested)))
                    output.extend(nested)
                    offset = payload_end
                elif wire == 5:
                    offset += 4
                    output.extend(data[field_start:offset])
                else:
                    raise ValueError('unsupported protobuf wire type')
        except (ValueError, IndexError):
            # A length-delimited value can be an ordinary string rather than
            # a nested message. Preserve it for callers that use this helper
            # with unrelated feature payloads.
            return data
        return bytes(output)

    return rewrite(protobuf)


def pack_feature_config(protobuf: bytes, vendor_tags: list[str]) -> bytes:
    """CameraConfigure.readIntFormStream uses network (big-endian) order."""
    protobuf = disable_portrait_mode(protobuf)
    tags = '|'.join(vendor_tags).encode('utf-8')
    return (struct.pack('>4i', 2001001, 2, 1, len(tags)) + tags
            + struct.pack('>2i', 2, len(protobuf)) + protobuf)


def virtual_media_profiles(data: bytes) -> bytes:
    root = ET.fromstring(data)
    for camera_id in ('0', '1'):
        camera = root.find(f"CamcorderProfiles[@cameraId='{camera_id}']")
        if camera is None:
            raise RuntimeError('Missing Ranchu camcorder profiles: ' + camera_id)
        template = camera.find("EncoderProfile[@quality='720p']")
        if template is None:
            raise RuntimeError('Missing Ranchu 720p profile: ' + camera_id)
        # ColorOS defaults to QUALITY_1080P (6). Ranchu's stock file has
        # only 720p; the OEM fallback retries 1080p and throws again.
        for quality, width, height, bitrate in (
                ('720p', 1280, 720, 6000000),
                ('1080p', 1920, 1080, 12000000),
                ('high', 1920, 1080, 12000000)):
            profile = camera.find(f"EncoderProfile[@quality='{quality}']")
            if profile is None:
                profile = copy.deepcopy(template)
                profile.set('quality', quality)
                camera.insert(0, profile)
            profile.set('fileFormat', 'mp4')
            profile.find('Video').attrib.update(
                codec='h264', bitRate=str(bitrate), width=str(width),
                height=str(height), frameRate='30')
            profile.find('Audio').attrib.update(
                codec='aac', bitRate='96000', sampleRate='48000', channels='1')
    h264 = root.find("VideoEncoderCap[@name='h264']")
    if h264 is not None:
        h264.attrib.update(maxFrameWidth='1920', maxFrameHeight='1080')
    ET.indent(root)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)
