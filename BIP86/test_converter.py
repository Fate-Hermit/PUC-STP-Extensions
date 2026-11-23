#!/usr/bin/env python3
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from convert_puc_bip import convert_one, verify_file


class ConversionTests(unittest.TestCase):
    def make_zip(self, path, name, content):
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('scp/'+name+'.txt', content)

    def run_conv(self, p, out, meta, overwrite=False):
        with zipfile.ZipFile(p) as z:
            member=z.infolist()[0]
            return convert_one(z,member,out,meta,20261023,'quarantine',overwrite=overwrite)

    def test_connected_and_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            td=Path(tmp); zp=td/'a.zip'; out=td/'out'; meta=td/'meta'
            # 2 rows, 3 columns, 4 nonzeros; costs must not affect edge weights.
            self.make_zip(zp,'sctest','2 3\n99 900 9\n2\n1 2\n2\n2 3\n')
            r=self.run_conv(zp,out,meta)
            self.assertEqual(r['edges'],4)
            self.assertEqual(r['terminal_components'],1)
            fu=out/'bipsctestu.stp';fp=out/'bipsctestp.stp'
            self.assertTrue(fu.is_file()); self.assertTrue(fp.is_file())
            u=verify_file(fu); p=verify_file(fp)
            self.assertTrue(u['feasible_for_stp']);self.assertTrue(p['feasible_for_stp'])
            self.assertEqual(u['weight_variant'],'u'); self.assertEqual(p['weight_variant'],'p')
            text=fu.read_text(encoding='utf-8')
            self.assertIn('E 1 3 1',text)
            self.assertIn('E 1 4 1',text)
            self.assertIn('E 2 4 1',text)
            self.assertIn('E 2 5 1',text)
            first=fp.read_bytes()
            r=self.run_conv(zp,out,meta)
            self.assertEqual(r['status'],'SKIPPED_VERIFIED')
            self.run_conv(zp,out,meta,overwrite=True)
            self.assertEqual(first,fp.read_bytes())

    def test_disconnect_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            td=Path(tmp);zp=td/'b.zip';out=td/'out';meta=td/'meta'
            self.make_zip(zp,'foo','2 2\n1 1\n1 1\n1 2\n')
            r=self.run_conv(zp,out,meta)
            self.assertEqual(r['terminal_components'],2)
            self.assertTrue((out/'infeasible'/'bipfoou.stp').exists())
            self.assertFalse((out/'bipfoou.stp').exists())
            self.assertEqual(json.loads((meta/'bipfoop.json').read_text(encoding='utf-8'))['stp_status'],'INFEASIBLE_FOR_STP')

    def test_invalid_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            td=Path(tmp);zp=td/'c.zip';out=td/'out';meta=td/'meta'
            self.make_zip(zp,'bad','2 2\n1 1\n2 1 1\n1 2\n')
            with self.assertRaises(ValueError):
                self.run_conv(zp,out,meta)
            self.assertFalse(any(out.rglob('*.stp')))


if __name__=='__main__': unittest.main(verbosity=2)
