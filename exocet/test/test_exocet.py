# Copyright (c) 2010-2011 Allen Short. See LICENSE file for details.
import sys
from unittest import TestCase
from exocet import (loadNamed, load, emptyMapper, pep302Mapper, getModule,
                    IMapper, DictMapper, ExclusiveMapper, proxyModule)
from zope.interface.verify import verifyObject

def assertIdentical(self, left, right):
    """
    Assert two expressions refer to the same object.
    """
    self.assertTrue(left is right, "%s is not %s" % (repr(left), repr(right)))


class ModuleTests(TestCase):
    """
    Tests for loading individual modules.
    """

    def test_loadNamed(self):
        """
        Modules can be loaded, by name, independent of global state.
        """
        m1 = loadNamed("exocet.test.testpackage.util", emptyMapper)
        m1.testAttribute = "a value"

        m2 = loadNamed("exocet.test.testpackage.util", emptyMapper)
        m2.testAttribute = "a different value"

        self.assertFalse(m1 is m2)
        self.assertNotEqual(m1.testAttribute, m2.testAttribute)
        self.assertFalse(m1 in sys.modules.values())
        self.assertFalse(m2 in sys.modules.values())
        self.assertEqual(m1.utilName, "hooray")
        self.assertEqual(m2.utilName, "hooray")


    def test_loadd(self):
        """
        Modules can be loaded independent of global state.
        """
        maker = getModule("exocet.test.testpackage.util")
        m1 = load(maker, emptyMapper)
        m1.testAttribute = "a value"

        m2 = load(maker, emptyMapper)
        m2.testAttribute = "a different value"

        self.assertFalse(m1 is m2)
        self.assertNotEqual(m1.testAttribute, m2.testAttribute)
        self.assertFalse(m1 in sys.modules.values())
        self.assertFalse(m2 in sys.modules.values())
        self.assertEqual(m1.utilName, "hooray")
        self.assertEqual(m2.utilName, "hooray")



class MapperTests(TestCase):
    """
    Tests for objects that map names used in C{import} statements to module
    objects.
    """

    def test_emptyMapper(self):
        """
        The empty mapper rejects all lookups.
        """
        verifyObject(IMapper, emptyMapper)
        for name in ["sys", "email", "exocet", "exocet.test"]:
            self.assertRaises(ImportError, emptyMapper.lookup, name)
            self.assertFalse(emptyMapper.contains(name))


    def test_dictMapper(self):
        """
        L{DictMapper} instances only map modules in the dict they wrap.
        """
        d = {"sys": object(), "exocet.test": object()}
        dm = DictMapper(d)
        verifyObject(IMapper, dm)
        for name in ["sys", "exocet.test"]:
            self.assertEqual(d[name], dm.lookup(name))
            self.assertTrue(dm.contains(name))

        for name in ["email", "foobaz"]:
            self.assertRaises(ImportError, dm.lookup, name)
            self.assertFalse(dm.contains(name))


    def test_exclusiveMapper(self):
        """
        L{ExclusiveMapper} implements an effective blacklist.
        """

        l = ["sys", "exocet.test"]
        em = ExclusiveMapper(pep302Mapper, l)

        verifyObject(IMapper, em)

        for name in l:
            self.assertRaises(ImportError, em.lookup, name)
            self.assertFalse(em.contains(name))


    def test_exclusiveMapperOverrides(self):
        """
        L{ExclusiveMapper} can be overriden.
        """

        l = ["sys", "exocet.test"]
        d = {"sys": object()}
        em = ExclusiveMapper(pep302Mapper, l).withOverrides(d)

        self.assertEqual(em.lookup("sys"), d["sys"])


    def test_pep302Mapper(self):
        """
        The L{pep302Mapper} looks up modules by invoking __import__.
        """
        import exocet, exocet.test, compiler.visitor
        pep302Mapper._oldSysModules = sys.modules.copy()
        verifyObject(IMapper, pep302Mapper)
        for (name, mod) in {"sys": sys,
                            "exocet": exocet,
                            "exocet.test": exocet.test,
                            "compiler.visitor": compiler.visitor}.iteritems():
            assertIdentical(self, pep302Mapper.lookup(name), mod)
            self.assertTrue(pep302Mapper.contains(name))

        self.assertRaises(ImportError, pep302Mapper.lookup,
                          "exocet._nonexistentModule")


    def test_overrides(self):
        """
        The L{pep302Mapper} supports overriding its mappings with a dict.
        """
        pep302Mapper._oldSysModules = sys.modules.copy()
        fakeMath = object()
        m = pep302Mapper.withOverrides({"math": fakeMath})
        self.assertTrue(m.contains("math"))
        self.assertTrue(m.contains("sys"))
        assertIdentical(self, m.lookup("math"), fakeMath)
        assertIdentical(self, m.lookup("sys"), sys)


    def test_ospath(self):
        """
        L{pep302Mapper} deals with modules that import L{os.path} properly.
        """

        m = loadNamed("exocet.test._ospathExample", pep302Mapper)
        import os.path
        assertIdentical(self, os, m.os)
        assertIdentical(self, os.path, m.os.path)


    def test_loadWithLocalImports(self):
        """
        Execution of local imports are resolved in the context the
        containing module was originally loaded in.
        """
        class fakeUtil:
            utilName = "booo"

        class tpli:
            util = fakeUtil
        m = pep302Mapper.withOverrides(
            {"exocet.test.testpackage_localimports": tpli})

        foo = loadNamed("exocet.test.testpackage_localimports.foo", m)
        self.assertEqual(foo.fooName, [])
        util2 = foo.do()
        self.assertEqual(foo.fooName[0], fakeUtil.utilName)
        self.assertEqual(util2.utilName, fakeUtil.utilName)


class MiscTests(TestCase):
    """
    Some other stuff.
    """

    def test_proxyModule(self):
        """
        L{proxyModule} creates a module wrapper, passing through all
        attributes accesses other than the overridden ones.
        """
        fakeStdout = object()
        sysEx = proxyModule(sys, stdout=fakeStdout)
        assertIdentical(self, sysEx.stdin, sys.stdin)
        assertIdentical(self, sysEx.stdout, fakeStdout)
