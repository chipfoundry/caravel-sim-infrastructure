import subprocess
import os
import sys


class DockerProcess:
    """Handles Docker image management with cleaner output."""
    
    # ANSI colors for terminal output
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    DIM = "\033[2m"
    ENDC = "\033[0m"
    
    def __init__(self, image_name, user_project_path=None, sim_path=None, quiet=False) -> None:
        self.image_name = image_name
        self.user_project_path = user_project_path
        self.sim_path = sim_path
        self.quiet = quiet
        self.use_colors = sys.stdout.isatty()

    def _print(self, msg, color="", dim=False):
        """Print with optional color, respecting quiet mode."""
        if self.quiet:
            return
        if self.use_colors and color:
            print(f"{color}{msg}{self.ENDC}")
        elif self.use_colors and dim:
            print(f"{self.DIM}{msg}{self.ENDC}")
        else:
            print(msg)

    def run(self):
        # pull/update docker image
        self.pull_docker_image()
        # update docker image with pip commands if requirements.txt exists
        if os.path.exists(
            f"{self.user_project_path}/verilog/dv/cocotb/requirements.txt"
        ):
            self.write_docker_file()
            self.build_docker_image()

    def pull_docker_image(self):
        # Check if the image exists locally
        try:
            subprocess.run(
                ["docker", "inspect", self.image_name],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._print(f"Checking for docker image updates...", dim=True)
            command = ["docker", "pull", "-q", f"{self.image_name}"]
        except subprocess.CalledProcessError:
            self._print(f"Pulling docker image {self.image_name}...", color=self.CYAN)
            command = ["docker", "pull", f"{self.image_name}"]
        except FileNotFoundError:
            self._print("Error: Docker is not installed.", color=self.RED)
            self._print("Please install Docker and try again.")
            exit(1)
        try:
            # Run the docker pull command (suppress output in quiet pull mode)
            result = subprocess.run(
                command, 
                check=True,
                stdout=subprocess.PIPE if "-q" in command else None,
                stderr=subprocess.PIPE if "-q" in command else None,
            )
        except subprocess.CalledProcessError as e:
            self._print(f"Error: Failed to pull {self.image_name}", color=self.RED)
            if not self.quiet:
                print(e)

    def build_docker_image(self):
        try:
            self._print(f"Building docker image with custom requirements...", dim=True)
            # Build the Docker image using subprocess (capture output)
            result = subprocess.run(
                [
                    "docker",
                    "build",
                    "-t",
                    self.image_name,
                    "-f",
                    f"{self.sim_path}/Dockerfile",
                    ".",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._print(f"Docker image ready.", color=self.GREEN)
        except subprocess.CalledProcessError as e:
            self._print(f"Error building Docker image: {e}", color=self.RED)

    def write_docker_file(self):
        with open(f"{self.sim_path}/Dockerfile", "w") as f:
            with open("requirements.txt", "r") as file:
                requirements = file.readlines()
            requirements = [requirement.strip() for requirement in requirements]

            f.write("# Use the chipfoundry/dv:cocotb base image\n")
            f.write("FROM chipfoundry/dv:cocotb\n")
            f.write("\n")
            # f.write("# Copy requirements.txt into the container\n")
            # f.write("WORKDIR /app\n")
            # f.write(f"COPY {self.user_project_path}/verilog/dv/cocotb/requirements.txt .\n")
            f.write("\n")
            f.write("# Install additional packages\n")
            f.write(f"RUN pip install --upgrade {' '.join(requirements)}")
            f.write("\n")
