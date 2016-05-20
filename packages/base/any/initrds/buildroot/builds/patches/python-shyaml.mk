######################################################################
##
## shyaml.mk
##
######################################################################

PYTHON_SHYAML_VERSION		= 0.4.0
PYTHON_SHYAML_SOURCE		= shyaml-$(PYTHON_SHYAML_VERSION).tar.gz
PYTHON_SHYAML_SITE		= https://github.com/0k/shyaml
PYTHON_SHYAML_INSTALL_STAGING	= NO
PYTHON_SHYAML_INSTALL_TARGET	= YES
PYTHON_SHYAML_LICENSE		= BSD-style
PYTHON_SHYAML_LICENSE_FILES	= LICENSE

##PYTHON_SHYAML_SETUP_TYPE	= setuptools
# Ugh, this buildroot is tool old to support this

PYTHON_SHYAML_DEPENDENCIES	= python python-yaml python-setuptools

# Ugh, this should be the default
_PYTHON_SHYAML_ENV		= \
   PYTHONPATH=$(TARGET_DIR)/usr/lib/python$(PYTHON_VERSION_MAJOR)/site-packages \
  # THIS LINE INTENTIONALLY LEFT BLANK

# Ugh, this 'setup.py install' bug was fixed in 
# https://github.com/jmesmon/buildroot/blob/master/package/python-setuptools/python-setuptools-add-executable.patch
# but buildroot uses a very old setuptools
_PYTHON_SHYAML_FIXUP_CMD		= \
  sed -i -e 's|^[\#].*python|\#!/usr/bin/python|' $(TARGET_DIR)/usr/bin/shyaml
  # THIS LINE INTENTIONALLY LEFT BLANK

define PYTHON_SHYAML_BUILD_CMD
  (cd $(@D); $(_PYTHON_SHYAML_ENV) $(HOST_DIR)/usr/bin/python setup.py build --executable /usr/bin/python)
endef

define PYTHON_SHYAML_INSTALL_TARGET_CMDS
  (cd $(@D) ;\
   $(_PYTHON_SHYAML_ENV) $(HOST_DIR)/usr/bin/python setup.py install --prefix=$(TARGET_DIR)/usr ;\
  $(_PYTHON_SHYAML_FIXUP_CMD) ;\
  :)
endef

$(eval $(generic-package))
##$$(eval $$(python-package))
# Ugh, this buildroot is tool old to support this

