"""Regression checks for the OEM config byte order and Ranchu recording profiles."""
from pathlib import Path
import struct
import json
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from coloros_camera_profiles import disable_portrait_mode, pack_feature_config, virtual_media_profiles
from build_coloros import virtual_camera_config


class ColorOSCameraConfigTests(unittest.TestCase):
    def test_virtual_capture_modes_have_one_camera_and_no_isp_tuning(self):
        source = {
            'camera_id_list': ['0', '1', '2', '3'],
            'mode_type_list': {'rear_main': ['photo_mode'], 'front_main': ['photo_mode']},
            'mode_operation_mode': {'professional_mode': '8020'},
            'feature_operation_mode': {'portrait_mode': {'bokeh': {'on': '8026'}}},
            'vendor_tag_type_values': {'com.oplus.tuning.data.buffer.support': '1', 'unrelated': 'keep'},
            'capture_stream_number': {'portrait_mode': {'rear_main': {'3dol': '3'}}},
            'usecase_info': {
                'sat_photo_case': [{'preview': 'rear_sat'}, {'capture_yuv': 'rear_main'}, {'capture_yuv': 'rear_wide'}],
                'front_single_photo_case': [{'preview': 'front_main'}, {'capture': 'front_main'}],
                'simple_preview_case': [{'preview': 'var_camera'}],
                'professional_case': [{'preview': 'rear_sat'}, {'capture_raw': 'rear_main'}],
                'portrait_bokeh_case': [{'preview': 'rear_main'}, {'preview': 'rear_wide'}],
                'telephoto_video_case': [{'preview': 'rear_telephoto'}, {'video_recorder': 'rear_telephoto'}],
            },
        }
        result = json.loads(virtual_camera_config(json.dumps(source).encode()))
        self.assertEqual(result['camera_id_list'], ['0', '1'])
        self.assertNotIn('portrait_mode', result['mode_type_list']['rear_main'])
        self.assertNotIn('portrait_mode', result['mode_type_list']['front_main'])
        self.assertEqual(result['mode_cameraType_sensor_number'], {})
        for case in ('sat_photo_case', 'front_single_photo_case', 'professional_case'):
            self.assertEqual(result['usecase_info'][case], [
                {'preview': 'var_camera'}, {'capture': 'var_camera'}])
        self.assertEqual(result['usecase_info']['portrait_bokeh_case'], [
            {'preview': 'var_camera'}, {'capture': 'var_camera'}])
        # "telephoto" contains "photo" but must retain its recording stream.
        self.assertEqual(result['usecase_info']['telephoto_video_case'], source['usecase_info']['telephoto_video_case'])
        self.assertEqual(result['vendor_tag_type_values']['com.oplus.tuning.data.buffer.support'], '0')
        self.assertEqual(result['vendor_tag_type_values']['unrelated'], 'keep')
        self.assertEqual(result['mode_operation_mode']['professional_mode'], '0')
        self.assertEqual(result['capture_stream_number'], {})

    def test_feature_envelope_matches_oem_big_endian_reader(self):
        payload = bytes.fromhex('0a06636f6d6d6f6e')
        packed = pack_feature_config(payload, ['feature:0', 'other:值'])
        version, count = struct.unpack_from('>2i', packed)
        self.assertEqual(version, 2001001)
        self.assertEqual(count, 2)
        offset, tags = 8, {}
        for _ in range(count):
            tag, size = struct.unpack_from('>2i', packed, offset)
            self.assertGreater(size, 0)
            offset += 8
            tags[tag] = packed[offset:offset + size]
            offset += size
        self.assertEqual(offset, len(packed))
        self.assertEqual(tags[1].decode(), 'feature:0|other:值')
        self.assertEqual(tags[2], payload)

    def test_portrait_mode_record_is_removed_without_removing_professional(self):
        def field(text):
            payload = text.encode()
            return bytes([0x0a, len(payload)]) + payload
        # Nested mode map: portrait and professional records are sibling fields.
        source = field('portrait_mode') + field('professional_mode')
        result = disable_portrait_mode(source)
        self.assertNotIn(b'portrait_mode', result)
        self.assertIn(b'professional_mode', result)

    def test_1080p_profiles_exist_for_both_cameras_and_preserve_other_ids(self):
        camera = '''<CamcorderProfiles cameraId="{id}">
          <EncoderProfile quality="720p" fileFormat="mp4" duration="60">
          <Video codec="h264" bitRate="1200000" width="1280" height="720" frameRate="30"/>
          <Audio codec="amrnb" bitRate="12200" sampleRate="8000" channels="1"/>
          </EncoderProfile></CamcorderProfiles>'''
        source = ('<MediaSettings>' + ''.join(camera.format(id=i) for i in (0, 1, 10))
                  + '<VideoEncoderCap name="h264" maxFrameWidth="1280" maxFrameHeight="720"/>'
                  + '</MediaSettings>').encode()
        result = ET.fromstring(virtual_media_profiles(source))
        for camera_id in (0, 1):
            profile = result.find(f"CamcorderProfiles[@cameraId='{camera_id}']/EncoderProfile[@quality='1080p']")
            self.assertIsNotNone(profile)
            self.assertEqual(profile.find('Video').get('width'), '1920')
            self.assertEqual(profile.find('Video').get('height'), '1080')
            self.assertEqual(profile.find('Audio').get('codec'), 'aac')
        self.assertIsNone(result.find("CamcorderProfiles[@cameraId='10']/EncoderProfile[@quality='1080p']"))
        self.assertEqual(result.find('VideoEncoderCap').get('maxFrameWidth'), '1920')


if __name__ == '__main__':
    unittest.main()
