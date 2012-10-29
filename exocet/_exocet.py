# -*- test-case-name: exocet.test.test_exocet -*-
# Copyright (c) 2010-2011 Allen Short. See LICENSE file for details.


import sys, __builtin__, itertools, traceback, functools
from exocet._modules import getModule
from types import ModuleType
from zope.interface import Interface, implements

DEBUG = False
_sysModulesSpecialCases = {
    "os": ['path'],
    "twisted.internet": ["reactor"],
}

def trace(*args):
    if DEBUG:
        print ' '.join(str(x) for x in args)


class IMapper(Interface):
    """
    An object that maps names used in C{import} statements to objects (such as
    modules).
    """

    def lookup(name):
        """
        Return a boolean indicating whether this name can be resolved
        sucessfully by this mapper.
        """


    def contains(name):
        """
        Return a boolean indicating whether this name can be resolved
        sucessfully by this mapper.
        """


    def withOverrides(overrides):
        """
        Create a new mapper based on this one, with the mappings provided
        overriding existing names.
        """


class CallableMapper(object):
    """
    A mapper based on a callable that returns a module or raises C{ImportError}.
    """
    implements(IMapper)
    def __init__(self, baseLookup):
        self._baseLookup = baseLookup


    def lookup(self, name):
        """
        Call our callable to do lookup.
        @see L{IMapper.lookup}
        """
        try:
            return self._baseLookup(name)
        except ImportError:
            raise ImportError("No module named %r in mapper %r" % (name, self))


    def contains(self, name):
        """
        @see L{IMapper.contains}
        """
        try:
            self.lookup(name)
            return True
        except ImportError:
            return False


    def withOverrides(self, overrides):
        """
        @see L{IMapper.withOverrides}
        """
        return _StackedMapper([DictMapper(overrides), self])


class DictMapper(object):
    """
    A mapper that looks up names in a dictionary or other mapping.
    """
    implements(IMapper)
    def __init__(self, _dict):
        self._dict = _dict


    def lookup(self, name):
        """
        @see L{IMapper.lookup}
        """
        if name in self._dict:
            trace("DictMapper imported %s as %s" % (name, self._dict[name]))
            return self._dict[name]
        else:
            raise ImportError("No module named %r in mapper %r" % (name, self))


    def contains(self, name):
        """
        @see L{IMapper.contains}
        """
        return name in self._dict


    def withOverrides(self, overrides):
        """
        @see L{IMapper.withOverrides}
        """
        return _StackedMapper([DictMapper(overrides), self])



class _StackedMapper(object):
    """
    A mapper that consults multiple other mappers, in turn.
    """

    def __init__(self, submappers):
        self._submappers = submappers


    def lookup(self, name):
        """
        @see L{IMapper.lookup}
        """
        for m in self._submappers:
            try:
                val = m.lookup(name)
                break
            except ImportError, e:
                continue
        else:
            raise e
        return val

    def contains(self, name):
        """
        @see L{IMapper.contains}
        """
        try:
            self.lookup(name)
            return True
        except ImportError:
            return False


    def withOverrides(self, overrides):
        """
        @see L{IMapper.withOverrides}
        """
        return _StackedMapper([DictMapper(overrides), self])



class ExclusiveMapper(object):
    """
    A mapper that wraps another mapper, but excludes certain names.

    This mapper can be used to implement a blacklist.
    """

    implements(IMapper)

    def __init__(self, submapper, excluded):
        self._submapper = submapper
        self._excluded = excluded


    def lookup(self, name):
        """
        @see l{Imapper.lookup}
        """

        if name in self._excluded:
            raise ImportError("Module %s blacklisted in mapper %s"
                % (name, self))
        return self._submapper.lookup(name)


    def contains(self, name):
        """
        @see l{Imapper.contains}
        """

        if name in self._excluded:
            return False
        return self._submapper.contains(name)


    def withOverrides(self, overrides):
        """
        @see L{IMapper.withOverrides}
        """
        return _StackedMapper([DictMapper(overrides), self])



def _noLookup(name):
    raise ImportError(name)

class _PEP302Mapper(CallableMapper):
    """
    Mapper that uses Python's default import mechanism to load modules.

    @cvar _oldSysModules: Set by L{_isolateImports} when clearing
    L{sys.modules} to its former contents.
    """

    _oldSysModules = {}

    def __init__(self):
        self._metaPath = list(sys.meta_path)


    def _baseLookup(self, name):
        try:
            prevImport = __import__
            prevMetaPath = list(sys.meta_path)
            prevSysModules = sys.modules.copy()
            __builtins__['__import__'] = prevImport
            sys.meta_path[:] = self._metaPath
            sys.modules.clear()
            sys.modules.update(self._oldSysModules)
            topLevel = _originalImport(name)
            trace("pep302Mapper imported %r as %r@%d" % (name, topLevel, id(topLevel)))
            packages = name.split(".")[1:]
            m = topLevel
            trace("subelements:", packages)
            for p in packages:
                trace("getattr", m, p)
                m = getattr(m, p)
            trace("done:", m, id(m))
            return m
        finally:
            self._oldSysModules.update(sys.modules)
            sys.meta_path[:] = prevMetaPath
            sys.modules.clear()
            sys.modules.update(prevSysModules)
            __builtins__['__import__'] = prevImport


emptyMapper = CallableMapper(_noLookup)
pep302Mapper = _PEP302Mapper()

def lookupWithMapper(mapper, fqn):
    """
    Look up a FQN in a mapper, logging all non-ImportError exceptions and
    converting them to ImportErrors.
    """
    try:
        return mapper.lookup(fqn)
    except ImportError, e:
        raise e
    except:
        print "Error raised by Exocet mapper while loading %r" % (fqn)
        traceback.print_exc()
        raise ImportError(fqn)



class ExocetModule(ModuleType):

    def __getattribute__(self, name):
        o = ModuleType.__getattribute__(self, name)
        if callable(o):
            @functools.wraps(o)
            def _localImportWrapper(*a, **kw):
                __builtin__.__import__ = redirectLocalImports
                try:
                    val = o(*a, **kw)
                finally:
                    __builtin__.__import__ = _originalImport
                return val
            return _localImportWrapper
        return o

class MakerFinder(object):
    """
    The object used as Exocet's PEP 302 meta-import hook. 'import' statements
    result in calls to find_module/load_module. A replacement for the
    C{__import__} function is provided as a method, as well.

    @ivar mapper: A L{Mapper}.

    @ivar oldImport: the implementation of C{__import__} being wrapped by this
                     object's C{xocImport} method.
    """
    def __init__(self, oldImport, mapper):
        self.mapper = mapper
        self.oldImport = oldImport


    def find_module(self, fullname, path=None):
        """
        Module finder nethod required by PEP 302 for meta-import hooks.

        @param fullname: The name of the module/package being imported.
        @param path: The __path__ attribute of the package, if applicable.
        """
        trace("find_module", fullname, path)
        return self


    def load_module(self, fqn):
        """
        Module loader method required by PEP 302 for meta-import hooks.

        @param fqn: The fully-qualified name of the module requested.
        """
        trace("load_module", fqn)
        trace("sys.modules", sys.modules)
        p = lookupWithMapper(self.mapper, fqn)
        trace("load_module", fqn, "done", id(p))

        if fqn in _sysModulesSpecialCases:
        # This module didn't have access to our isolated sys.modules when it
        # did its sys.modules modification. Replicate it here.
            for submoduleName in _sysModulesSpecialCases[fqn]:
                subfqn = '.'.join([fqn, submoduleName])
                sys.modules[subfqn] = getattr(p, submoduleName, None)
        return p


    def xocImport(self, name, *args, **kwargs):
        """
        Wrapper around C{__import__}. Needed to ensure builtin modules aren't
        loaded from the global context.
        """
        trace("Import invoked:", name, kwargs.keys())
        if name in sys.builtin_module_names:
            trace("Loading builtin module", name)
            return self.load_module(name)
        else:
            return self.oldImport(name, *args, **kwargs)




def loadNamed(fqn, mapper, m=None):
    """
    Load a Python module, eliminating as much of its access to global state as
    possible. If a package name is given, its __init__.py is loaded.

    @param fqn: The fully qualified name of a Python module, e.g
    C{twisted.python.filepath}.

    @param mapper: A L{Mapper}.

    @param m: An optional empty module object to load code into. (For
    resolving circular module imports.)

    @returns: An instance of the module name requested.
    """
    maker = getModule(fqn)
    return load(maker, mapper, m=m)


def load(maker, mapper, m=None):
    """
    Load a Python module, eliminating as much of its access to global state as
    possible. If a package name is given, its __init__.py is loaded.

    @param maker: A module maker object (i.e., a L{modules.PythonModule} instance)

    @param mapper: A L{Mapper}.

    @param m: An optional empty module object to load code into. (For
    resolving circular module imports.)

    @returns: An instance of the module name requested.
    """
    mf = MakerFinder(__builtin__.__import__, mapper)
    if maker.filePath.splitext()[1] in [".so", ".pyd"]:
        #it's native code, gotta suck it up and load it globally (really at a
        ## loss on how to unit test this without significant inconvenience)
        return maker.load()
    return _isolateImports(mf, _loadSingle, maker, mf, m)

def _loadSingle(mk, mf, m=None):
    trace("execfile", mk.name, m)
    if m is None:
        m = ExocetModule(mk.name)
    contents = {}
    code = execfile(mk.filePath.path, contents)
    contents['__exocet_context__'] = mf
    m.__dict__.update(contents)
    m.__file__ = mk.filePath.path
    return m

def _isolateImports(mf, f, *a, **kw):
    """
    Internal guts for actual code loading. Displaces the global environment
    and executes the code, then restores the previous global settings.

    @param mk: A L{modules._modules.PythonModule} object; i.e., a module
    maker.
    @param mf: A L{MakerFinder} instance.
    @param m: An optional empty module object to load code into. (For resolving
    circular module imports.)
    """


    oldMetaPath = sys.meta_path
    oldPathHooks = sys.path_hooks
    _PEP302Mapper._oldSysModules = sys.modules.copy()
    oldImport = __builtin__.__import__
    #where is your god now?
    sys.path_hooks = []
    sys.modules.clear()
    sys.meta_path = [mf]
    __builtins__['__import__'] = mf.xocImport



    #stupid special case for the stdlib
    if mf.mapper.contains('warnings'):
        sys.modules['warnings'] = mf.mapper.lookup('warnings')

    try:
       return f(*a, **kw)
    finally:
        sys.meta_path = oldMetaPath
        sys.path_hooks = oldPathHooks
        sys.modules.clear()
        sys.modules.update(_PEP302Mapper._oldSysModules)
        __builtins__['__import__'] = oldImport


def _buildAndStoreEmptyModule(maker, mapper):
    m = ModuleType(maker.name)
    m.__path__ = maker.filePath.path
    mapper.add(maker.name, m)
    return m


def proxyModule(original, **replacements):
    """
    Create a proxy for a module object, overriding some of its attributes with
    replacement objects.

    @param original: A module.
    @param replacements: Attribute names and objects to associate with them.

    @returns: A module proxy with attributes containing the replacement
    objects; other attribute accesses are delegated to the original module.
    """
    class _ModuleProxy(object):
       def __getattribute__(self, name):
           if name in replacements:
               return replacements[name]
           else:
               return getattr(original, name)

       def __repr__(self):
           return "<Proxy for %r: %s replaced>" % (
               original, ', '.join(replacements.keys()))
    return _ModuleProxy()




def redirectLocalImports(name, globals=None, *a, **kw):
    """
    Catch function-level imports in modules loaded via Exocet. This ensures
    that any imports done after module load time look up imported names in the
    same context the module was originally loaded in.
    """
    if globals is not None:
        mf = globals.get('__exocet_context__', None)
        if mf is not None:
            trace("isolated __import__ of", name,  "called in exocet module", mf, mf.mapper)
            return _isolateImports(mf, _originalImport, name, globals, *a, **kw)
        else:
            return _originalImport(name, globals, *a, **kw)
    else:
        return _originalImport(name, globals, *a, **kw)

_originalImport = __builtin__.__import__
