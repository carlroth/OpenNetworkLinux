#!/usr/bin/python
############################################################
#
# Extended YAML Support
#
# Supports include files and variable interpolations.
#
############################################################
import yaml
import os, sys
import pprint
import tempfile
from string import Template
import types
import onlu

logger = onlu.init_logging('onlyaml')
expand = True
strict = True

class OnlYamlError(Exception):
    """General Error Exception"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value

class OnlTemplateError(OnlYamlError):
    """Error thrown during template expansion.

    Template expansion is iteratively retried as
    the YAML tree is being populated.
    """
    pass

BuiltinLoader = yaml.loader.Loader
class Loader(BuiltinLoader):
    """Custom YAML loader supporing variable interpolation.

    Scoop up the top-level 'variables' dict to use as an interpolation
    source, but only if 'root' is None (that is, not during include
    or script processing of the non-root node)
    """

    def __init__(self, stream, defaults=None, overrides=None, root=None):
        BuiltinLoader.__init__(self, stream)

        self.defaults = defaults
        self.overrides = overrides

        self.variables = None
        # variables parsed from the YAML document

        self.root = root
        # only grab the yaml variables dict if root=None

    def construct_document(self, node):

        data = self.construct_object(node)

        def _scan():
            """Capture top-level 'variables' dict for substitution

            Depending on the traversal order of the generators, the root Loader
            generators may be exhausted by the time the 'variables' dict is encountered...
            Here we need to seed a dummy generator event into the root Loader
            to force the 'variables' dict to be re-scanned.
            """
            if self.root is None and self.variables is None and 'variables' in data:
                logger.debug("found the root variables dict")
                self.variables = data['variables']
            elif self.root is not None and 'variables' in data:
                logger.debug("found a candidate variables dict")
                def fn():
                    yield
                self.root.state_generators.append(fn())

        while self.state_generators:
            state_generators = self.state_generators
            self.state_generators = []
            logger.debug("processing %d generators in %s",
                         len(state_generators), self.name)
            for generator in state_generators:
                for dummy in generator:
                    pass
                _scan()

        self.constructed_objects = {}
        self.recursive_objects = {}
        self.deep_construct = False
        return data

    def getContext(self, overrides=None):
        ctx = {}
        if self.defaults is not None:
            ctx.update(self.defaults)
        if self.variables is not None:
            ctx.update(self.variables)
        if self.root is not None and self.root.variables is not None:
            ctx.update(self.root.variables)
        if self.overrides is not None:
            ctx.update(self.overrides)
        if overrides is not None:
            ctx.update(overrides)
        return ctx

    def interpolate(self, val, overrides=None):

        ctx = self.getContext(overrides=overrides)
        tpl = Template(val)
        try:
            nval = tpl.substitute(ctx)
        except KeyError as e:
            error_string = "Yaml variable substitution error: '%s' could not be resolved in '%s'."
            raise OnlTemplateError(error_string % (e.args[0], val,))

        if val != nval:
            logger.debug("substitute %s --> %s", val, nval)

        return nval

    def subLoader(self, overrides=None):
        """Loader factory with predefine variable scope."""
        ctx = self.getContext(overrides=overrides)
        root = self.root or self
        def _fact(stream):
            return self.__class__(stream, overrides=ctx, root=root)
        return _fact

    @classmethod
    def withVariables(cls, variables, root=None):
        """Loader factory with predefine variable scope."""
        def _fact(stream):
            return cls(stream, defaults=variables, root=root)
        return _fact

class LazyString(str):
    """Lazy string scalar type.

    The actual string value can be initialized after the fact,
    as the YAML variables are discovered.
    """

    UNDEFINED = "THIS STRING INTENTIONALLY LEFT BLANK"
    def __new__(cls, data=None):
        inst = str.__new__(cls, cls.UNDEFINED)
        inst.data = data
        return inst

    def __init__(self, data=None):
        self.data = data

    def __str__(self):
        if self.data is None:
            raise ValueError("lazy string is not initialized")
        if self.data == self.UNDEFINED:
            raise ValueError("lazy string is not initialized")
        return self.data

    def __repr__(self):
        if self.data is None:
            return "<LazyString (None)>"
        if self.data == self.UNDEFINED:
            return "<LazyString (undefined)>"
        return repr(self.data)

class LazyUnicode(unicode):
    """Lazy unicode scalar type.

    The actual string value can be initialized after the fact,
    as the YAML variables are discovered.
    """

    UNDEFINED = "THIS UNICODE STRING INTENTIONALLY LEFT BLANK"
    def __new__(cls, data=None):
        inst = str.__new__(cls, cls.UNDEFINED)
        inst.data = data
        return inst

    def __init__(self):
        self.data = None

    def __str__(self):
        if self.data is None:
            raise ValueError("lazy unicode is not initialized")
        if self.data == self.UNDEFINED:
            raise ValueError("lazy unicode is not initialized")
        return self.data

    def __repr__(self):
        if self.data is None:
            return "<LazyUnicode (None)>"
        if self.data == self.UNDEFINED:
            return "<LazyUnicode (undefined)>"
        return repr(self.data)

class LazyTemplate:
    """Implement generators to perform template expansion.

    The generator protocol for the yaml constructors assumes
    1. the first item returned from the generator is either a final,
       scalar value, or an empty (mutable) container for that value.
    2. further items retrieved from the generator are thrown away,
       they are indented to trigger recursive constructors as a side-effect
    3. further computation can be deferred by adding a generator object
       to the end of loader.state_generators,
       though the act of constructing a generator in the first place
       usually requires an initial 'yield' statement,
       or one buried in some unreachable code :-)

    Template expansion takes advantage of (3) by deferring/retrying
    a failed template expansion in the hopes that further processing
    of the constructors will fill in the template values.

    Currently we try failed templates up to 5 times, this should allow
    for most template expansions to proceed. This can be better formalized
    by keeping track of a generation ID in the loader(s) to track
    expansion process.
    """
    def __init__(self, loader, val, data=None, tries=5):
        self.loader = loader
        self.val = val
        self.data = data
        self.tries = tries

    def start(self):

        if self.data:
            raise ValueError("start() called on LazyTemplate with invalid data")

        try:
            nval = self.loader.interpolate(self.val)
        except OnlTemplateError:
            nval = None

        # short-cut to scalar if fully-formed
        if nval is not None and self.data is None:
            yield nval
            return

        # initialize the lazy container data type and prepare for iteration
        if self.data is None and nval is None:
            if type(self.val) == str:
                self.data = LazyString()
            elif type(self.val) == unicode:
                self.data = LazyUnicode()
            else:
                raise ValueError("invalid string type for %s in %s"
                                 % (repr(self.val), self.loader.name,))
            yield self.data

        # else, continue iterating with a deferred generator
        logger.debug("interpolation of %s --> %s in %s failed on try %d, will keep trying",
                     self.val, nval, self.loader.name, self.tries)

        # else, retry using ourselves (in another loop)
        self.loader.state_generators.append(self.defer())

    def defer(self):

        if self.tries <= 0:
            if strict:
                raise OnlTemplateError("cannot expand template '%s' in %s"
                                       % (self.val, self.loader.name,))
            else:
                logger.warn("cannot expand template '%s' in %s",
                            self.val, self.loader.name)
                self.data.data = self.val
                return

        if self.data is not None and self.data.data is not None:
            raise NotImplementedError("already substituted")

        try:
            self.data.data = self.loader.interpolate(self.val)
            return
        except OnlTemplateError:
            pass

        self.tries -= 1
        gen = self.defer()

        # try to process the states in the root document
        if self.loader.root is not None:
            self.loader.root.state_generators.append(gen)
        else:
            self.loader.state_generators.append(gen)
        return

        yield
        # mark this function body as an iterator

BuiltinDumper = yaml.dumper.Dumper
class Dumper(BuiltinDumper):

    def represent_lazy_string(self, data):
        """Lazy strings are represented as simple strings."""
        return self.represent_str(data.data)

    def represent_lazy_unicode(self, data):
        """Lazy strings are represented as simple strings."""
        return self.represent_unicode(data.data)

Dumper.add_representer(LazyString, Dumper.represent_lazy_string)
Dumper.add_representer(LazyUnicode, Dumper.represent_lazy_unicode)

class StringMixin:

    @classmethod
    def from_yaml(cls, loader, node):
        val = yaml.constructor.Constructor.construct_yaml_str(loader, node)
        if expand:
            return LazyTemplate(loader, val).start()
        else:
            return val

    @classmethod
    def to_yaml(cls, dumper, data):
        return yaml.representer.Representer.represent_string(dumper, data)

class StringNode(StringMixin, yaml.YAMLObject):
    """Override the default str type to support interpolation."""
    yaml_tag = u'tag:yaml.org,2002:str'

class UnicodeNode(StringMixin, yaml.YAMLObject):
    """Override the default Python unicode type to support interpolation."""
    yaml_tag = u'tag:yaml.org,2002:python/unicode'

class TemplateMixin:

    @classmethod
    def getString(cls, loader, node):
        """Local template expansion for a str node.

        Fails if not all tags are available (possible bug).
        """
        val = StringNode.from_yaml(loader, node)
        if isinstance(val, types.GeneratorType):
            gen, val = val, val.next()
            if not isinstance(val, basestring):
                raise OnlYamlError("Cannot invoke script '%s' in %s, pending expansions"
                                   % (val, loader.name,))
        return val

class ScriptNode(TemplateMixin, yaml.YAMLObject):

    yaml_tag = u'!script'

    @classmethod
    def from_yaml(cls, loader, node):
        """XXX roth -- no support for deferred template expansion here.

        The main problem that if we decide to defer the computation,
        we do not know the final data type of the output.
        """
        val = cls.getString(loader, node)
        tf = tempfile.NamedTemporaryFile()
        tf.close()
        if os.system("%s > %s" % (val, tf.name)) != 0:
            raise OnlYamlError("Script execution '%s' failed." % val)
        try:
            with open(tf.name) as fd:
                return yaml.load(fd, Loader=loader.subLoader())
        finally:
            os.unlink(tf.name)

class IncludeNode(TemplateMixin, yaml.YAMLObject):

    yaml_tag = u'!include'

    @classmethod
    def from_yaml(cls, loader, node):
        """XXX roth -- no support for deferred template expansion here.

        XXX roth -- include rudimentary expansion as shown above
        """

        variables = {}

        if isinstance(node, yaml.ScalarNode):

            directive = cls.getString(loader, node)
            fields = directive.split()
            fname = fields[0]
            options = fields[1:]

            for opt in options:
                k, s, v = opt.partition('=')
                if s:
                    variables[k] = v;
                else:
                    raise OnlYamlError("Bad include directive: %s" % opt)

        elif isinstance(node, yaml.MappingNode):

            for k, v in node.value:
                v = cls.getString(v)
                if k.tag == 'tag:yaml.org,2002:value':
                    # key '=' in map
                    fname = v
                elif k.tag == 'tag:yaml.org,2002:str':
                    variables[k.value] = v
                else:
                    raise OnlYamlError("Invalid include directive: %s (%s)"
                                       % (k.value, k.tag,))

        else:
            raise OnlYamlError("Include file '%s' (from %s) has invalid format."
                               % (fname, loader.name))

        if not os.path.isabs(fname):
            fname = os.path.join(os.path.dirname(loader.name), fname)

        if not os.path.exists(fname):
            raise OnlYamlError("Include file '%s' (from %s) does not exist."
                               % (fname, loader.name))

        with open(fname) as fd:
            return yaml.load(fd, loader.subLoader(variables))

def loadf(fname, vard={}):

    variables = {}

    # Files can reference environment variables
    for k, v in os.environ.iteritems():
        try:
            v = v.encode('ascii')
        except UnicodeEncodeError:
            pass
        variables[k] = v

    # Files can reference their own directory.
    variables['__DIR__'] = os.path.dirname(os.path.abspath(fname))

    # Files can reference invokation parameters.
    variables.update(vard)

    with open(fname) as fd:
        try:
            return yaml.load(fd, Loader=Loader.withVariables(variables))
        except OnlYamlError, e:
            raise e

def dump(data):
    return yaml.dump(data, Dumper=Dumper)

if __name__ == '__main__':
    import sys
    try:
        if len(sys.argv) == 2:
            sys.stdout.write(dump(loadf(sys.argv[1])))
        else:
            logger.error("usage: %s <yamlfile>", sys.argv[0])
    except OnlYamlError, e:
        logger.error("error: %s", e.value)
        sys.exit(1)
