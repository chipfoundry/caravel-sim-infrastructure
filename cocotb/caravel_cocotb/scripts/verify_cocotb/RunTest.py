import os
import shutil
import subprocess
from caravel_cocotb.scripts.verify_cocotb.read_defines import GetDefines
import re
import logging
import caravel_cocotb
import hashlib
from caravel_cocotb.scripts.verify_cocotb.logging_config import OutputFilter, Colors


class RunTest:
    COMPILE_LOCK = set()

    def __init__(self, args, paths, test, logger) -> None:
        self.args = args
        self.paths = paths
        self.test = test
        self.logger = logger

    def run_test(self):
        # OpenFrame mode: no firmware/hex generation needed
        if self.args.openframe:
            self.runTest()
        elif self.hex_generate() == "hex_generated":  # run test only if hex is generated
            self.runTest()
        if not self.args.compile_only:
            self.test.end_of_test()

    def docker_command_str(
        self,
        docker_image="chipfoundry/dv:cocotb",
        docker_dir="",
        env_vars="",
        addtional_switchs="",
        command="",
    ):
        command = f"docker run {' --init -it --sig-proxy=true ' if not self.args.CI else ' '} -u $(id -u $USER):$(id -g $USER) {addtional_switchs} {env_vars} {docker_dir} {docker_image} sh -ec '{command}'"
        return command

    def hex_riscv_command_gen(self):
        GCC_PATH = "/opt/riscv/bin/"
        GCC_PREFIX = "riscv32-unknown-elf"
        GCC_COMPILE = f"{GCC_PATH}/{GCC_PREFIX}"
        SOURCE_FILES = (
            f"{self.paths.FIRMWARE_PATH}/crt0_vex.S {self.paths.FIRMWARE_PATH}/isr.c"
        )

        LINKER_SCRIPT = f"-Wl,-Bstatic,-T,{self.test.linker_script_file},--strip-debug "
        CPUFLAGS = "-O2 -g -march=rv32i_zicsr -mabi=ilp32 -D__vexriscv__ -ffreestanding -nostdlib"
        # CPUFLAGS = "-O2 -g -march=rv32imc_zicsr -mabi=ilp32 -D__vexriscv__ -ffreestanding -nostdlib"
        includes = [f"-I{ip}" for ip in self.get_ips_fw()] + [
            f"-I{self.paths.FIRMWARE_PATH}",
            f"-I{self.paths.FIRMWARE_PATH}/APIs",
            f"-I{self.paths.USER_PROJECT_ROOT}/verilog/dv/cocotb",
            f"-I{self.paths.VERILOG_PATH}/dv/generated",
            f"-I{self.paths.VERILOG_PATH}/dv/",
            f"-I{self.paths.VERILOG_PATH}/common/",
        ]
        includes = f" -I{self.paths.FIRMWARE_PATH} -I{self.paths.FIRMWARE_PATH}/APIs -I{self.paths.VERILOG_PATH}/dv/generated  -I{self.paths.VERILOG_PATH}/dv/ -I{self.paths.VERILOG_PATH}/common"
        includes += f" -I{self.paths.USER_PROJECT_ROOT}/verilog/dv/cocotb {' '.join([f'-I{ip}' for ip in self.get_ips_fw()])}"
        elf_command = (
            f"{GCC_COMPILE}-gcc  {includes} {CPUFLAGS} {LINKER_SCRIPT}"
            f" -o {self.hex_dir}/{self.test.name}.elf {SOURCE_FILES} {self.c_file}"
        )
        lst_command = f"{GCC_COMPILE}-objdump -d -S {self.hex_dir}/{self.test.name}.elf > {self.hex_dir}/{self.test.name}.lst "
        hex_command = f"{GCC_COMPILE}-objcopy -O verilog {self.hex_dir}/{self.test.name}.elf {self.hex_dir}/{self.test.name}.hex "
        sed_command = f'sed -ie "s/@10/@00/g" {self.hex_dir}/{self.test.name}.hex'
        return f" {elf_command} && {lst_command} && {hex_command} && {sed_command}"

    def hex_arm_command_gen(self):
        GCC_COMPILE = "arm-none-eabi"
        SOURCE_FILES = f"{self.paths.FIRMWARE_PATH}/cm0_start.s"
        LINKER_SCRIPT = f"-T {self.test.linker_script_file}"
        CPUFLAGS = "-O2 -Wall -nostdlib -nostartfiles -ffreestanding -mcpu=cortex-m0 -Wno-unused-value"
        includes = f"-I{self.paths.FIRMWARE_PATH} -I{self.paths.USER_PROJECT_ROOT}/verilog/dv/cocotb"
        elf_command = (
            f"{GCC_COMPILE}-gcc  {includes} {CPUFLAGS} {LINKER_SCRIPT}"
            f" -o {self.hex_dir}/{self.test.name}.elf {SOURCE_FILES} {self.c_file}"
        )
        lst_command = f"{GCC_COMPILE}-objdump -d -S {self.hex_dir}/{self.test.name}.elf > {self.hex_dir}/{self.test.name}.lst "
        hex_command = f"{GCC_COMPILE}-objcopy -O verilog {self.hex_dir}/{self.test.name}.elf {self.hex_dir}/{self.test.name}.hex "
        sed_command = f'sed -ie "s/@10/@00/g" {self.hex_dir}/{self.test.name}.hex'
        return f" {elf_command} &&{lst_command}&& {hex_command}&& {sed_command}"

    def hex_generate(self) -> str:
        # get the test path from dv/cocotb
        test_path = self.test_path()
        # Create a new hex_files directory because it does not exist
        if not os.path.exists(f"{self.paths.SIM_PATH}/hex_files"):
            os.makedirs(f"{self.paths.SIM_PATH}/hex_files")
        self.hex_dir = f"{self.paths.SIM_PATH}/hex_files/"
        self.c_file = f"{test_path}/{self.test.name}.c"
        if self.args.cpu_type == "ARM":
            command = self.hex_arm_command_gen()
        else:
            command = self.hex_riscv_command_gen()

        docker_dir = f"-v {self.hex_dir}:{self.hex_dir} -v {self.paths.RUN_PATH}:{self.paths.RUN_PATH} -v {self.paths.CARAVEL_ROOT}:{self.paths.CARAVEL_ROOT} "
        if "MCW_ROOT" in self.paths._fields:
            docker_dir += f"-v {self.paths.MCW_ROOT}:{self.paths.MCW_ROOT} "
        docker_dir += f"-v {self.test.test_dir}:{self.test.test_dir} {' '.join([f'-v {link}:{link} ' for link in self.get_ips_fw()])} "
        docker_dir = (
            docker_dir
            + f"-v {self.paths.USER_PROJECT_ROOT}:{self.paths.USER_PROJECT_ROOT}"
        )
        docker_command = self.docker_command_str(
            docker_image="chipfoundry/dv:cocotb", docker_dir=docker_dir, command=command
        )
        # don't run with docker with arm
        cmd = command if self.args.cpu_type == "ARM" else docker_command
        hex_gen_state = self.run_command_write_to_file(
            cmd,
            self.test.hex_log,
            self.logger,
            quiet=False if self.args.verbosity == "debug" else True,
        )
        self.firmware_log = open(self.test.hex_log, "a")
        if hex_gen_state != 0:
            # open(self.test.firmware_log, "w").write(stdout)
            raise RuntimeError(
                f"{bcolors.FAIL}Error:{bcolors.ENDC} Fail to compile the C code for more info refer to {bcolors.OKCYAN}{self.test.hex_log}{bcolors.ENDC} "
            )
            self.firmware_log.write("Error: when generating hex")
            self.firmware_log.close()
            return "hex_error"
        self.firmware_log.write("Pass: hex generation")
        self.firmware_log.close()
        # move hex file to the test
        shutil.copyfile(
            f"{self.test.hex_dir}/{self.test.name}.hex",
            f"{self.test.test_dir}/firmware.hex",
        )
        return "hex_generated"

    def get_ips_fw(self, flag_type="-I"):
        fw_list = []
        if not os.path.exists(f"{self.paths.USER_PROJECT_ROOT}/ip"):
            return fw_list
        for file in os.listdir(f"{self.paths.USER_PROJECT_ROOT}/ip"):
            if os.path.isdir(f"{self.paths.USER_PROJECT_ROOT}/ip/{file}"):
                for f in os.listdir(f"{self.paths.USER_PROJECT_ROOT}/ip/{file}"):
                    if f == "fw":
                        fw_list.append(
                            os.path.realpath(
                                f"{self.paths.USER_PROJECT_ROOT}/ip/{file}/{f}"
                            )
                        )
        # send it as string
        # ips_fw = f"{flag_type}" + f" {flag_type}".join(fw_list)
        return fw_list

    def test_path(self, test_name=None):
        if test_name is None:
            test_name = self.test.name
        c_file_name = test_name + ".c"
        tests_path_user = os.path.abspath(
            f"{self.paths.USER_PROJECT_ROOT}/verilog/dv/cocotb"
        )
        test_file = self.find(c_file_name, tests_path_user)
        test_path = os.path.dirname(test_file)
        return test_path

    def runTest(self):
        os.environ["COCOTB_RESULTS_FILE"] = f"{self.test.test_dir}/seed.xml"
        if self.args.iverilog:
            self.runTest_iverilog()
        elif self.args.vcs:
            self.runTest_vcs()
        # elif self.args.verilator:
        # self.runTest_verilator()

    # iverilog function
    def runTest_iverilog(self):
        if self.test.sim == "GL_SDF":
            raise RuntimeError(
                f"{bcolors.FAIL}iverilog can't run SDF for test {self.test.name} Please use anothor simulator like cvc{bcolors.ENDC}"
            )
            return
        self.write_iverilog_includes_file()
        if not os.path.isfile(f"{self.test.compilation_dir}/sim.vvp"):
            print(f"{bcolors.OKCYAN}Compiling as sim.vvp not found{bcolors.ENDC}")
            self.iverilog_compile()
            self.write_hash(self.test.netlist)
        elif self.args.compile:
            print(f"{bcolors.OKCYAN}Compiling as compile flag is set{bcolors.ENDC}")
            self.iverilog_compile()
            self.write_hash(self.test.netlist)
        elif (
            not self.is_same_hash(self.test.netlist)
            and f"{self.test.compilation_dir}/sim.vvp" not in RunTest.COMPILE_LOCK
        ):
            print(f"{bcolors.OKCYAN}Compiling since netlist has changed{bcolors.ENDC}")
            self.iverilog_compile()
        else:
            if f"{self.test.compilation_dir}/sim.vvp" not in RunTest.COMPILE_LOCK:
                print(
                    f"{bcolors.OKGREEN}Skipping compilation as netlist has not changed{bcolors.ENDC}"
                )
        RunTest.COMPILE_LOCK.add(
            f"{self.test.compilation_dir}/sim.vvp"
        )  # locked means if it is copiled for the first time then it will not be compiled again even if netlist changes
        if not self.args.compile_only:
            self.iverilog_run()

    def write_iverilog_includes_file(self):
        self.iverilog_dirs = " "
        self.iverilog_dirs += f"-I {self.paths.USER_PROJECT_ROOT}/verilog/rtl"
        self.test.set_user_project()
        for include_dir in self.test.include_dirs:
            self.iverilog_dirs += f" -I {include_dir}"

    def iverilog_compile(self):
        if os.path.isfile(f"{self.test.compilation_dir}/sim.vvp"):
            os.remove(f"{self.test.compilation_dir}/sim.vvp")
        macros = " -D" + " -D".join(self.test.macros)
        # Top-level module is always caravel_top - the OPENFRAME macro controls which design is instantiated
        top_module = "caravel_top"
        toplevel_file = f"{self.paths.CARAVEL_VERILOG_PATH}/rtl/toplevel_cocotb.v"
        compile_command = (
            f"cd {self.test.compilation_dir} &&"
            f"iverilog -g2012 -Ttyp {macros} {self.iverilog_dirs} -o {self.test.compilation_dir}/sim.vvp -s {top_module}"
            f" {toplevel_file}"
        )
        docker_compilation_command = self._iverilog_docker_command_str(compile_command)
        self.run_command_write_to_file(
            docker_compilation_command if not self.args.no_docker else compile_command,
            self.test.compilation_log,
            self.logger,
            quiet=False if self.args.verbosity == "debug" else True,
        )

    def iverilog_run(self):
        defines = GetDefines(self.test.includes_file)
        seed = "" if self.args.seed is None else f"RANDOM_SEED={self.args.seed}"
        run_command = f"cd {self.test.test_dir} && TESTCASE={self.test.name} MODULE=module_trail {seed} vvp -M $(cocotb-config --prefix)/cocotb/libs -m libcocotbvpi_icarus {self.test.compilation_dir}/sim.vvp +{' +'.join(self.test.macros)} {' '.join([f'+{k}={v}' if v != '' else f'+{k}' for k, v in defines.defines.items()])}"
        docker_run_command = self._iverilog_docker_command_str(run_command)
        self.run_command_write_to_file(
            docker_run_command if not self.args.no_docker else run_command,
            None if self.args.verbosity == "quiet" else self.test.test_log2,
            self.logger,
            quiet=True if self.args.verbosity == "quiet" else False,
        )

    def _iverilog_docker_command_str(self, command=""):
        """the docker command without the command that would run"""
        # Build environment variables - handle OpenFrame (no VERILOG_PATH from MCW)
        if self.args.openframe:
            env_vars = f"-e COCOTB_RESULTS_FILE={os.getenv('COCOTB_RESULTS_FILE')} -e CARAVEL_PATH={self.paths.CARAVEL_PATH} -e CARAVEL_VERILOG_PATH={self.paths.CARAVEL_VERILOG_PATH} -e PDK_ROOT={self.paths.PDK_ROOT} -e PDK={self.paths.PDK} -e USER_PROJECT_VERILOG={self.paths.USER_PROJECT_ROOT}/verilog -e OPENFRAME=1"
        else:
            env_vars = f"-e COCOTB_RESULTS_FILE={os.getenv('COCOTB_RESULTS_FILE')} -e CARAVEL_PATH={self.paths.CARAVEL_PATH} -e CARAVEL_VERILOG_PATH={self.paths.CARAVEL_VERILOG_PATH} -e VERILOG_PATH={self.paths.VERILOG_PATH} -e PDK_ROOT={self.paths.PDK_ROOT} -e PDK={self.paths.PDK} -e USER_PROJECT_VERILOG={self.paths.USER_PROJECT_ROOT}/verilog"
        local_caravel_cocotb_path = caravel_cocotb.__file__.replace("__init__.py", "")
        docker_caravel_cocotb_path = (
            "/usr/local/lib/python3.10/dist-packages/caravel_cocotb/"
        )
        # Build volume mounts - skip MCW_ROOT for OpenFrame
        docker_dir = f"-v {self.paths.RUN_PATH}:{self.paths.RUN_PATH} -v {self.paths.CARAVEL_ROOT}:{self.paths.CARAVEL_ROOT} "
        if not self.args.openframe and "MCW_ROOT" in self.paths._fields:
            docker_dir += f"-v {self.paths.MCW_ROOT}:{self.paths.MCW_ROOT} "
        docker_dir += f"-v {self.paths.PDK_ROOT}:{self.paths.PDK_ROOT} -v {local_caravel_cocotb_path}:{docker_caravel_cocotb_path} "
        docker_dir += (
            f"-v {self.paths.USER_PROJECT_ROOT}:{self.paths.USER_PROJECT_ROOT}"
        )
        docker_dir += " ".join(
            [
                f" -v {link}:{link} "
                for link in self.find_symbolic_links(self.paths.USER_PROJECT_ROOT)
            ]
        )
        if os.path.exists("/mnt/scratch/"):
            docker_dir += " -v /mnt/scratch/cocotb_runs/:/mnt/scratch/cocotb_runs/ "
        display = " -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v $HOME/.Xauthority:/.Xauthority --network host --security-opt seccomp=unconfined "
        command = self.docker_command_str(
            docker_image="chipfoundry/dv:cocotb",
            docker_dir=docker_dir,
            env_vars=env_vars,
            addtional_switchs=display,
            command=command,
        )
        return command

    def find_symbolic_links(self, directory):
        sym_links = []
        for root, dirs, files in os.walk(directory):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                if os.path.islink(dir_path):
                    sym_links.append(dir_path)
        return sym_links

    # vcs function
    def runTest_vcs(self):
        self.write_vcs_includes_file()
        self.vcs_coverage_command = ""
        if self.test.sim == "RTL":
            self.vcs_coverage_command = "-cm line+tgl+cond+fsm+branch+assert "
        os.environ["TESTCASE"] = f"{self.test.name}"
        os.environ["MODULE"] = "module_trail"
        if not os.path.isfile(f"{self.test.compilation_dir}/simv"):
            print(f"{bcolors.OKCYAN}Compiling as simv not found{bcolors.ENDC}")
            self.vcs_compile()
            self.write_hash(self.test.netlist)
        elif self.args.compile:
            print(f"{bcolors.OKCYAN}Compiling as compile flag is set{bcolors.ENDC}")
            self.vcs_compile()
            self.write_hash(self.test.netlist)
        elif (
            not self.is_same_hash(self.test.netlist)
            and f"{self.test.compilation_dir}/simv" not in RunTest.COMPILE_LOCK
        ):
            print(
                f"{bcolors.OKCYAN}Compiling since netlist has has changed{bcolors.ENDC}"
            )
            self.vcs_compile()
        else:
            if f"{self.test.compilation_dir}/simv" not in RunTest.COMPILE_LOCK:
                print(
                    f"{bcolors.OKCYAN}Skipping compilation as netlist has not changed{bcolors.ENDC}"
                )
        RunTest.COMPILE_LOCK.add(
            f"{self.test.compilation_dir}/simv"
        )  # locked means if it is copiled for the first time then it will not be compiled again even if netlist changes
        if not self.args.compile_only:
            self.vcs_run()

    def write_vcs_includes_file(self):
        # self.vcs_dirs = f'+incdir+\\"{self.paths.PDK_ROOT}/{self.paths.PDK}\\" '
        self.vcs_dirs = " "
        if self.test.sim == "RTL":
            self.vcs_dirs += (
                f'+incdir+\\"{self.paths.USER_PROJECT_ROOT}/verilog/rtl\\" '
            )
        self.test.set_user_project()

    def vcs_compile(self):
        if os.path.isfile(f"{self.test.compilation_dir}/simv"):
            os.remove(f"{self.test.compilation_dir}/simv")
        macros = " +define+" + " +define+".join(self.test.macros)
        # Top-level module is always caravel_top - the OPENFRAME macro controls which design is instantiated
        top_module = "caravel_top"
        toplevel_file = f"{self.paths.CARAVEL_VERILOG_PATH}/rtl/toplevel_cocotb.v"
        vlogan_cmd = f"cd {self.test.compilation_dir}; vlogan -full64 -sverilog +error+30 {toplevel_file} {self.vcs_dirs}  {macros}   -l {self.test.compilation_dir}/analysis.log -o {self.test.compilation_dir} "
        self.run_command_write_to_file(
            vlogan_cmd,
            self.test.compilation_log,
            self.logger,
            quiet=False if self.args.verbosity == "debug" else True,
        )
        lint = "+lint=all" if self.args.lint else ""
        ignored_errors = " -error=noZMMCM "
        vcs_cmd = f"cd {self.test.compilation_dir};  vcs {lint} -negdelay {self.vcs_coverage_command} {ignored_errors} -debug_access+all +error+50 +vcs+loopreport+1000000 -diag=sdf:verbose +sdfverbose +neg_tchk -full64  -l {self.test.compilation_dir}/test_compilation.log  {top_module} -Mdir={self.test.compilation_dir}/csrc -o {self.test.compilation_dir}/simv +vpi -P pli.tab -load $(cocotb-config --lib-name-path vpi vcs)"
        self.run_command_write_to_file(
            vcs_cmd,
            self.test.compilation_log,
            self.logger,
            quiet=False if self.args.verbosity == "debug" else True,
        )

    def vcs_run(self):
        defines = GetDefines(self.test.includes_file)
        if self.args.seed is not None:
            os.environ["RANDOM_SEED"] = self.args.seed
        run_sim = f"cd {self.test.test_dir}; {self.test.compilation_dir}/simv +vcs+dumpvars+all {self.vcs_coverage_command} -cm_name {self.test.name} +{' +'.join(self.test.macros)} {' '.join([f'+{k}={v}' if v != '' else f'+{k}' for k, v in defines.defines.items()])}"
        self.run_command_write_to_file(
            run_sim,
            None if self.args.verbosity == "quiet" else self.test.test_log2,
            self.logger,
            quiet=True if self.args.verbosity == "quiet" else False,
        )

    def find(self, name, path):
        for root, dirs, files in os.walk(path):
            if name in files:
                return os.path.join(root, name)
        raise RuntimeError(f"Test {name} doesn't exist or don't have a C file ")

    def run_command_write_to_file(self, cmd, file, logger, quiet=True):
        """Run command and write output to file, return 0 if no error.
        
        Improvements:
        - Filters out noisy output (docker volumes, platform warnings)
        - Deduplicates progressive line output (truncated + full)
        - Only shows important messages in normal mode
        """
        # Patterns to filter out from console (always log to file)
        noise_patterns = [
            re.compile(r'^-v\s+/'),  # Docker volume mounts
            re.compile(r'docker\.io/'),  # Docker image refs
            re.compile(r"What's next:"),
            re.compile(r'docker scout'),
            re.compile(r'View a summary of image'),
            re.compile(r'platform.*does not match'),
            re.compile(r'^\s*$'),  # Empty lines
            re.compile(r'DeprecationWarning'),  # Python deprecation warnings
            re.compile(r'RuntimeWarning'),  # Runtime warnings
            re.compile(r'^\*+$'),  # Lines of just asterisks
            re.compile(r'^\*\*\s'),  # Cocotb table lines starting with **
            re.compile(r'^\s+\*\*'),  # Cocotb table continuation lines
            re.compile(r'cocotb\.scheduler\.add'),  # Scheduler deprecation
            re.compile(r'/usr/local/lib/python.*\.py:\d+:'),  # Python path warnings with line numbers
            re.compile(r'^\s+cocotb\.(scheduler|log)'),  # Cocotb internal refs
            re.compile(r'===WARNING===.*sky130'),  # SKY130 timing warnings
            re.compile(r'^VCD info:'),  # VCD file info
            re.compile(r'^\s+self\.'),  # Stack trace lines starting with self.
            re.compile(r'^/opt/homebrew/'),  # Homebrew path warnings
            re.compile(r'gpi_embed\.cpp'),  # GPI embed messages
            re.compile(r'GpiCommon\.cpp'),  # GPI common messages
            re.compile(r'in gpi_print_registered'),  # GPI registration
            re.compile(r'in set_program_name_in_venv'),  # venv detection
            re.compile(r'VPI registered'),  # VPI registration
            re.compile(r'pytest not found'),  # Pytest suggestion
        ]
        
        # Set up file logging separately
        log_file = None
        if file is not None:
            log_file = open(file, "a")
            log_file.write("command:\n")
            log_file.write(os.path.expandvars(cmd) + "\n\n")
            log_file.write("-" * 60 + "\n")
        
        # Buffered deduplication: hold each line and only print when we see a different line
        # This handles progressive output (truncated -> medium -> full)
        # Key: only deduplicate when one line is a STRICT PREFIX of another
        buffered_line = None
        
        def is_progressive_duplicate(line1, line2):
            """Check if line1 is a truncated version of line2 (strict prefix)."""
            if not line1 or not line2:
                return False
            # One must be a strict prefix of the other (progressive output)
            # This is NOT the same as sharing a common prefix
            shorter, longer = (line1, line2) if len(line1) < len(line2) else (line2, line1)
            # The shorter line must be a prefix of the longer line
            # And they must differ by at least a few characters (not just whitespace)
            if longer.startswith(shorter) and len(longer) > len(shorter) + 2:
                return True
            return False
        
        def flush_buffer():
            """Print the buffered line if there is one."""
            nonlocal buffered_line
            if buffered_line is not None:
                print(buffered_line)
                buffered_line = None
        
        try:
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            
            ansi_escape = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")
            
            while True:
                out = process.stdout.readline()
                if not out and process.poll() is not None:
                    break
                if out:
                    try:
                        line = out.decode("utf-8")
                    except UnicodeDecodeError:
                        line = out.decode("latin-1")
                    
                    # Strip ANSI codes for clean output
                    clean_line = ansi_escape.sub("", line).rstrip()
                    
                    # Always log to file (full output)
                    if log_file is not None and clean_line:
                        log_file.write(clean_line + "\n")
                        log_file.flush()
                    
                    # Only show to console if not quiet and not noise
                    if not quiet and clean_line:
                        is_noise = any(p.search(clean_line) for p in noise_patterns)
                        
                        if not is_noise:
                            if is_progressive_duplicate(clean_line, buffered_line):
                                # Progressive duplicate - keep the longer one
                                if len(clean_line) > len(buffered_line or ""):
                                    buffered_line = clean_line
                                # else: current is shorter, keep buffered (it's longer)
                            else:
                                # Different line - flush buffer and start new
                                flush_buffer()
                                buffered_line = clean_line
            
            # Flush any remaining buffered line
            flush_buffer()
                            
        except KeyboardInterrupt:
            logger.warning("Process interrupted by user")
            process.terminate()
        except Exception as e:
            logger.error(f"Process error: {e}")
            try:
                process.terminate()
            except:
                pass
        finally:
            if log_file is not None:
                log_file.close()

        return process.returncode

    @staticmethod
    def calculate_netlist_hash(netlist, hash_algorithm="sha256"):
        """Calculate a combined hash of multiple files ignoring the order."""
        hash_func = getattr(hashlib, hash_algorithm)()
        try:
            for file_path in sorted(netlist):  # Ensure consistent order
                with open(file_path, "rb") as f:
                    while chunk := f.read(8192):
                        hash_func.update(chunk)
            return hash_func.hexdigest()
        except FileNotFoundError as e:
            return f"File not found: {e.filename}"
        except PermissionError as e:
            return f"Permission denied: {e.filename}"

    def is_same_hash(self, netlist):
        # read old hash if exists
        try:
            with open(self.test.hash_log, "r") as f:
                old_hash = f.read().strip()
        except FileNotFoundError:
            old_hash = 0
        # calculate new hash
        new_hash = self.write_hash(netlist)
        return new_hash == old_hash

    def write_hash(self, netlist):
        new_hash = self.calculate_netlist_hash(netlist)
        with open(self.test.hash_log, "w") as f:
            f.write(new_hash)
        return new_hash


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def change_str(str, new_str, file_path):
    # Read in the file
    with open(file_path, "r") as file:
        filedata = file.read()

    filedata = filedata.replace(str, new_str)

    # Write the file out again
    with open(file_path, "w") as file:
        file.write(filedata)
