"""
The ``plugin`` module implements a sophisticated, featureful plugin loader
based on Exocet, with interface-based discovery.
"""

from types import ModuleType
from xml.sax import saxutils

from exocet import ExclusiveMapper, getModule, load, pep302Mapper

from twisted.internet import reactor
from twisted.python import log

from zope.interface import invariant, Attribute, Interface
from zope.interface.exceptions import BrokenImplementation
from zope.interface.exceptions import BrokenMethodImplementation
from zope.interface.verify import verifyObject


class InvariantException(Exception):
    """
    Exception raised by failed invariant conditions.
    """

class PluginException(Exception):
    """
    Signal an error encountered during plugin handling.
    """


class IBravoPlugin(Interface):
    """
    Interface for plugins.

    This interface stores common metadata used during plugin discovery.
    """

    name = Attribute("""
        The name of the plugin.

        This name is used to reference the plugin in configurations, and also
        to uniquely index the plugin.
        """)

def sorted_invariant(s):
    intersection = set(s.before) & set(s.after)
    if intersection:
        raise InvariantException("Plugin wants to come before and after %r" %
            intersection)

class ISortedPlugin(IBravoPlugin):
    """
    Parent interface for sorted plugins.

    Sorted plugins have an innate and automatic ordering inside lists thanks
    to the ability to advertise their dependencies.
    """

    invariant(sorted_invariant)

    before = Attribute("""
        Plugins which must come before this plugin in the pipeline.

        Should be a tuple, list, or some other iterable.
        """)

    after = Attribute("""
        Plugins which must come after this plugin in the pipeline.

        Should be a tuple, list, or some other iterable.
        """)


blacklisted = set([
    "asyncore",        # Use Twisted's event loop.
    "ctypes",          # Segfault protection.
    "gc",              # Haha, no.
    "imp",             # Haha, no.
    "inspect",         # Haha, no.
    "multiprocessing", # Use Twisted's process interface.
    "socket",          # Use Twisted's socket interface.
    "subprocess",      # Use Twisted's process interface.
    "thread",          # Use Twisted's thread interface.
    "threading",       # Use Twisted's thread interface.
])
overrides = {
    "twisted.internet.reactor": reactor,
    "saxutils": saxutils,
}
bravoMapper = ExclusiveMapper(pep302Mapper,
                              blacklisted).withOverrides(overrides)

def sort_plugins(plugins):
    """
    Make a sorted list of plugins by dependency.

    If the list cannot be arranged into a DAG, an error will be raised. This
    usually means that a cyclic dependency was found.

    :raises PluginException: cyclic dependency detected
    """

    l = []
    d = dict((plugin.name, plugin) for plugin in plugins)

    def visit(plugin):
        if plugin not in l:
            for name in plugin.before:
                if name in d:
                    visit(d[name])
            l.append(plugin)

    for plugin in plugins:
        if not any(name in d for name in plugin.after):
            visit(plugin)

    return l

def add_plugin_edges(d):
    """
    Mirror edges to all plugins in a dictionary.
    """

    for plugin in d.itervalues():
        plugin.after = set(plugin.after)
        plugin.before = set(plugin.before)

    for name, plugin in d.iteritems():
        for edge in list(plugin.before):
            if edge in d:
                d[edge].after.add(name)
            else:
                plugin.before.discard(edge)
        for edge in list(plugin.after):
            if edge in d:
                d[edge].before.add(name)
            else:
                plugin.after.discard(edge)

    return d

def expand_names(plugins, names):
    """
    Given a list of names, expand wildcards and discard disabled names.

    Used to implement * and - options in plugin lists.

    :param dict plugins: plugins to use for expansion
    :param list names: names to examine

    :returns: a list of filtered plugin names
    """

    wildcard = False
    exceptions = set()
    expanded = set()

    # Partition the list into exceptions and non-exceptions, finding the
    # wildcard(s) along the way.
    for name in names:
        if name == "*":
            wildcard = True
        elif name.startswith("-"):
            exceptions.add(name[1:])
        else:
            expanded.add(name)

    if wildcard:
        # Add all of the plugin names to the expanded name list.
        expanded.update(plugins.keys())

    # Remove excepted names from the expanded list.
    names = list(expanded - exceptions)

    return names

def verify_plugin(interface, plugin):
    """
    Plugin interface verification.

    This function will call ``verifyObject()`` and ``validateInvariants()`` on
    the plugins passed to it.

    The primary purpose of this wrapper is to do logging, but it also permits
    code to be slightly cleaner, easier to test, and callable from other
    modules.
    """

    try:
        verifyObject(interface, plugin)
        interface.validateInvariants(plugin)
        log.msg(" ( ^^) Plugin: %s" % plugin.name)
    except BrokenImplementation, bi:
        if hasattr(plugin, "name"):
            log.msg(" ( ~~) Plugin %s is missing attribute %r!" %
                (plugin.name, bi.name))
        else:
            log.msg(" ( >&) Plugin %s is unnamed and useless!" % plugin)
    except BrokenMethodImplementation, bmi:
        log.msg(" ( Oo) Plugin %s has a broken %s()!" % (plugin.name,
            bmi.method))
        log.msg(bmi)
    except InvariantException, ie:
        log.msg(" ( >&) Plugin %s failed validation!" % plugin.name)
        log.msg(ie)
    else:
        return plugin

    raise PluginException("Plugin failed verification")

def synthesize_parameters(parameters):
    """
    Create a faked module which has the given parameters in it.

    This should work everywhere. If it doesn't, let me know.
    """

    module = ModuleType("parameters")
    module.__dict__.update(parameters)
    return module

__cache = {}

def get_plugins(interface, package, parameters=None):
    """
    Lazily find objects in a package which implement a given interface.

    If the optional dictionary of parameters is provided, it will be passed
    into each plugin module as the "bravo.parameters" module. An example
    access from inside the plugin:

    >>> from bravo.parameters import foo, bar

    Since the parameters are available as a real module, the parameters may be
    imported and used like any other module:

    >>> from bravo import parameters as params

    This is a rewrite of Twisted's ``twisted.plugin.getPlugins`` which uses
    Exocet instead of Twisted to find the plugins.

    :param interface interface: the interface to match against
    :param str package: the name of the package to search
    :param dict parameters: parameters to pass into the plugins
    """

    mapper = bravoMapper

    # If parameters are provided, add them to the mapper in a synthetic
    # module.
    if parameters:
        mapper = mapper.withOverrides(
            {"bravo.parameters": synthesize_parameters(parameters)})

    # This stack will let us iteratively recurse into packages during the
    # module search.
    stack = [getModule(package)]

    # While there are packages left to search...
    while stack:
        # For each package/module in the package...
        for pm in stack.pop().iterModules():
            # If it's a package, append it to the list of packages to search.
            if pm.isPackage():
                stack.append(pm)

            try:
                # Load the module.
                m = load(pm, mapper)

                # Make a good attempt to iterate through the module's
                # contents, and see what matches our interface.
                for obj in vars(m).itervalues():
                    try:
                        adapted = interface(obj, None)
                    except:
                        log.err()
                    else:
                        if adapted is not None:
                            yield adapted
            except ImportError, ie:
                log.msg(ie)
            except SyntaxError, se:
                log.msg(se)

def retrieve_plugins(interface, parameters=None):
    """
    Look up all plugins for a certain interface.

    If the plugin cache is enabled, this function will not attempt to reload
    plugins from disk or discover new plugins.

    :param interface interface: the interface to use
    :param dict parameters: parameters to pass into the plugins

    :returns: a dict of plugins, keyed by name
    :raises PluginException: no plugins could be found for the given interface
    """

    if not parameters and interface in __cache:
        return __cache[interface]

    log.msg("Discovering %s..." % interface)
    d = {}
    for p in get_plugins(interface, "bravo.plugins", parameters):
        try:
            verify_plugin(interface, p)
            d[p.name] = p
        except PluginException:
            pass

    if issubclass(interface, ISortedPlugin):
        # Sortable plugins need their edges mirrored.
        d = add_plugin_edges(d)

    # Cache non-parameterized plugins.
    if not parameters:
        __cache[interface] = d

    return d

def retrieve_named_plugins(interface, names, parameters=None):
    """
    Look up a list of plugins by name.

    Plugins are returned in the same order as their names.

    :param interface interface: the interface to use
    :param list names: plugins to find
    :param dict parameters: parameters to pass into the plugins

    :returns: a list of plugins
    :raises PluginException: no plugins could be found for the given interface
    """

    d = retrieve_plugins(interface, parameters)

    # Handle wildcards and options.
    names = expand_names(d, names)

    try:
        return [d[name] for name in names]
    except KeyError, e:
        raise PluginException("Couldn't find plugin %s for interface %s!" %
            (e.args[0], interface.__name__))

def retrieve_sorted_plugins(interface, names, parameters=None):
    """
    Look up a list of plugins, sorted by interdependencies.

    :param dict parameters: parameters to pass into the plugins
    """

    l = retrieve_named_plugins(interface, names, parameters)
    try:
        return sort_plugins(l)
    except KeyError, e:
        raise PluginException("Couldn't find plugin %s for interface %s!" %
            (e.args[0], interface))
