""" mamba building block """

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function

from distutils.version import LooseVersion
import logging
import posixpath

import hpccm.config
import hpccm.templates.rm
import hpccm.templates.wget
import hpccm.templates.tar

from hpccm.building_blocks.base import bb_base
from hpccm.building_blocks.packages import packages
from hpccm.common import cpu_arch
from hpccm.primitives.comment import comment
from hpccm.primitives.copy import copy
from hpccm.primitives.shell import shell
from hpccm.primitives.environment import environment


class mamba(bb_base, hpccm.templates.rm, hpccm.templates.wget, hpccm.templates.tar):
    """The `mamba` building block installs Mamba.


    """

    def __init__(self, **kwargs):

        super(mamba, self).__init__(**kwargs)

        self.__arch_pkg = ""  # Filled by __cpu_arch()
        self.__base_url = kwargs.get("baseurl", "https://micromamba.snakepit.net/api/micromamba")
        self.__channels = kwargs.get('channels', list())
        self.__environment = kwargs.get('environment', None)

        self.__ospackages = kwargs.get('ospackages', ['ca-certificates', 'wget'])
        self.__packages = kwargs.get('packages', list())
        self.__environment_name = kwargs.get("environment_name", '')
        self.__prefix = kwargs.get('prefix', '/opt/conda')

        self.__commands = []  # Filled in by __setup()
        self.__wd = kwargs.get('wd', hpccm.config.g_wd)  # working directory

        # Set the CPU architecture specific parameters
        self.__cpu_arch()

        # Construct the series of steps to execute
        self.__setup()

        # Fill in container instructions
        self.__instructions()

    def __instructions(self):
        """Fill in container instructions"""

        self += comment('Mamba')
        self += environment(variables={"MAMBA_ROOT_PREFIX": "/opt/conda"})
        if self.__environment:
            self += copy(src=self.__environment, dest=posixpath.join(
                self.__wd, posixpath.basename(self.__environment)))
        self += packages(ospackages=self.__ospackages)
        self += shell(commands=self.__commands)

    def __cpu_arch(self):
        """Based on the CPU architecture, set values accordingly.  A user
        specified value overrides any defaults."""

        if hpccm.config.g_cpu_arch == cpu_arch.PPC64LE:
            self.__arch_pkg = "ppc64le"
        elif hpccm.config.g_cpu_arch == cpu_arch.X86_64:
            self.__arch_pkg = "64"
        elif hpccm.config.g_cpu_arch == cpu_arch.AARCH64:
            self.__arch_pkg = "aarch64"
        else:  # pragma: no cover
            raise RuntimeError('Unknown CPU architecture')

    def __setup(self):
        """Construct the series of shell commands, i.e., fill in self.__commands"""
        # Check version
        micromamba_distribution = "linux-{0}/latest".format(self.__arch_pkg)
        url = "{0}/{1}".format(self.__base_url, micromamba_distribution)

        # Download sources from web
        self.__commands.append(
            self.download_step(
                url=url,
                directory=self.__wd,
                outfile=posixpath.join(self.__wd, "micromamba.tar.bz2")
            )
        )
        self.__commands.append(
            self.untar_step(
                posixpath.join(self.__wd, "micromamba.tar.bz2"),
                directory=posixpath.join(self.__prefix)
            )
        )

        # Initialize mamba
        micromamba = posixpath.join(self.__prefix, "bin", "micromamba")
        self.__commands.append(
            "touch /root/.bashrc"
        )
        self.__commands.append(
            "{0} shell init --shell bash -p {1}".format(
                micromamba,
                self.__prefix
            )
        )
        self.__commands.append(
            "grep -v '[ -z \"\\$PS1\" ] && return' /root/.bashrc  > {0}/.bashrc".format(self.__prefix)
        )
        # self.__commands.append(
        #     "ln -s {0} /etc/profile.d/micromamba".format(micromamba)
        # )

        # Activate
        # if self.__channels or self.__environment or self.__packages:
        #     self.__commands.append(
        #         "echo \"micromamba activate\" >> /root/.bashrc"
        #     )

        # Enable channels
        _mamba_config = "/root/.mambarc"
        self.__commands.append(
            "touch {0}".format(_mamba_config)
        )
        self.__commands.append(
            "echo \"channels:\" > {0}".format(_mamba_config)
        )
        if len(self.__channels) == 0:
            # Need to have one (default) channel
            self.__channels.append("conda-forge")

        for channel in self.__channels:
            self.__commands.append(
                "echo \"  - {0}\" >> {1}".format(channel, _mamba_config)
            )

        # # Install environment
        if self.__environment:
            self.__commands.append(
                "{0} create -y -f {1}".format(
                    micromamba,
                    posixpath.join(self.__wd, posixpath.basename(self.__environment)),
                )
            )
            # self.__commands.append(
            #     "grep '^name:' environment.yml | awk '{print $2}' | xargs conda activate"
            # )
            self.__commands.append(
                self.cleanup_step(
                    items=[posixpath.join(self.__wd, posixpath.basename(self.__environment))]
                )
            )

        # Install conda packages
        if self.__packages:
            if not self.__environment_name:
                raise ValueError("An environment name should be given for the packages to be installed in!")
            self.__commands.append(
                "{0} create -y -n {1} {2}".format(
                    micromamba,
                    self.__environment_name,
                    ' '.join(sorted(self.__packages))
                )
            )
            self.__commands.append(
                "{0} activate {1}".format(micromamba, self.__environment_name)
            )
            # self.__commands.append('micromamba install -y {}'.format(
            #     ' '.join(sorted(self.__packages))))

        # Cleanup conda install
        self.__commands.append(
            "{0} clean -afy".format(micromamba)
        )

        # Advanced cleanup of packages
        conda_env_path = posixpath.join(self.__prefix, "envs", self.__environment_name)
        self.__commands.append(
            self.cleanup_step(
                items=[
                    posixpath.join(conda_env_path, "bin", "sqlite3"),
                    posixpath.join(conda_env_path, "bin", "openssl"),
                    posixpath.join(conda_env_path, "share", "terminfo"),
                ]
            )
        )
        _find_string = "find {0}/lib/python*/site-packages -type d"
        _exec_rm_string = " -exec rm -rf '{}' '+'"
        self.__commands.extend([
            _find_string.format(conda_env_path) + " -name \"pip\"" + _exec_rm_string,
            _find_string.format(conda_env_path) + " -name \"tests\"" + _exec_rm_string,
            _find_string.format(conda_env_path) + " -name \"*.pyx\"" + _exec_rm_string,
            "find {0}/lib/python*/ -type d".format(conda_env_path) + " -name \"ensurepip\"" + _exec_rm_string,
            "find {0}/lib/python*/ -type d".format(conda_env_path) + " -name \"idlelib\"" + _exec_rm_string,
        ])

        # Cleanup micromamba download file
        self.__commands.append(
            "apt-get clean autoremove --yes"
        )
        self.__commands.append(self.cleanup_step(items=["/var/lib/{apt,dpkg,cache,log}"]))

    def runtime(self, _from='0'):
        """Generate the set of instructions to install the runtime specific
        components from a build in a previous stage.

        # Examples

        ```python
        c = mamba(...)
        Stage0 += c
        Stage1 += c.runtime()
        ```
        """
        self.rt += comment('Mamba')
        self.rt += copy(_from=_from, src=self.__prefix, dest=self.__prefix)
        self.rt += copy(_from=_from, src="/root/.bashrc", dest="/root/.bashrc")
        self.rt += environment(variables={"PATH": "{0}:$PATH".format(posixpath.join(self.__prefix, 'bin'))})

        self.rt += shell(
            commands=[
                "echo \"source {0}/etc/profile.d/micromamba.sh\" >> ~/.bashrc".format(self.__prefix),
                "echo \"{0} activate {1}\" >> ~/.bashrc".format("micromamba", self.__environment_name)
            ]
        )
        return str(self.rt)
