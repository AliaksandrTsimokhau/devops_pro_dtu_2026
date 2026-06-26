# Container Scanning Configuration Tutorial

This tutorial guides you through configuring container scanning in your pipeline:

1. [Create a new project](#create-a-new-project)
2. [Add a Dockerfile](#add-a-dockerfile-to-new-project)
3. [Create pipeline configuration](#create-pipeline-configuration)
4. [Check for reported vulnerabilities](#check-for-reported-vulnerabilities)
5. [Update the Docker image and rescan](#update-the-docker-image)

---

## Create a New Project

To create a new project:

1. On the left sidebar, at the top, select **Create new** ( ![plus icon]( ) ) and **New project/repository**.
2. Select **Create blank project**.
3. In **Project name**, enter `Tutorial container scanning project`.
4. In **Project URL**, select a namespace for the project.
5. Select **Create project**.

---

## Add a Dockerfile to New Project

To provide something for container scanning to work on, create a minimal Dockerfile:

1. In your `Tutorial container scanning project`, select **New file**.
2. Enter the filename `Dockerfile`, and provide the following contents:

    ```dockerfile
    FROM hello-world:latest
    ```

    Docker images created from this Dockerfile are based on the `hello-world` Docker image.

3. Select **Commit changes**.

---

## Create Pipeline Configuration

Now you’re ready to create the pipeline configuration. The pipeline will:

- Build a Docker image from the `Dockerfile` and push it to the container registry.
- Include the `Container-Scanning.gitlab-ci.yml` template to scan the Docker image.

To create the pipeline configuration:

1. In the root directory of your project, select **New file**.
2. Enter the filename `.gitlab-ci.yml`, and provide the following contents:

    ```yaml
    trivy:
      stage: test
      image: docker:stable
      services:
        - name: docker:dind
          entrypoint: ["env", "-u", "DOCKER_HOST"]
          command: ["dockerd-entrypoint.sh"]
      variables:
        DOCKER_HOST: tcp://docker:2375/
        DOCKER_DRIVER: overlay2
        # See https://github.com/docker-library/docker/pull/166
        DOCKER_TLS_CERTDIR: ""
        IMAGE: trivy-ci-test:$CI_COMMIT_SHA
        TRIVY_NO_PROGRESS: "true"
        TRIVY_CACHE_DIR: ".trivycache/"
      before_script:
        - export TRIVY_VERSION=$(wget -qO - "https://api.github.com/repos/aquasecurity/trivy/releases/latest" | grep '"tag_name":' | sed -E 's/.*"v([^"]+)".*/\1/')
        - echo $TRIVY_VERSION
        - wget --no-verbose https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz -O - | tar -zxvf -
      allow_failure: true
      script:
        # Build image
        - docker build -t $IMAGE .
        # Build report
        - ./trivy image --exit-code 0 --format template --template "@/contrib/gitlab.tpl" -o gl-container-scanning-report.json $IMAGE
        # Print report
        - ./trivy image --exit-code 0 --severity HIGH $IMAGE
        # Fail on severe vulnerabilities
        - ./trivy image --exit-code 1 --severity CRITICAL $IMAGE
        cache:
            paths:
            - .trivycache/
        # Enables https://docs.gitlab.com/ee/user/application_security/container_scanning/ (Container Scanning report is available on GitLab Ultimate)
        artifacts:
            reports:
            container_scanning: gl-container-scanning-report.json
    ```

3. Select **Commit changes**.

After you commit the file, a new pipeline starts with this configuration. When it’s finished, you can check the results of the scan.

---

## Check for Reported Vulnerabilities

Vulnerabilities for a scan are located on the pipeline that ran the scan. To check for reported vulnerabilities:

1. Select **CI/CD > Pipelines** and select the most recent pipeline. This pipeline should have a job called `container_scanning` in the test stage.
2. If the `container_scanning` job was successful, select the **Security** tab. If any vulnerabilities were found, they are listed on that page.

---

## Update the Docker Image

A Docker image based on `hello-world:latest` is unlikely to show any vulnerabilities. For an example of a scan that reports vulnerabilities:

1. In the root directory of your project, select the existing `Dockerfile` file.
2. Select **Edit**.
3. Replace `FROM hello-world:latest` with a different Docker image for the `FROM` instruction. The best Docker images to demonstrate container scanning have:
    - Operating system packages (e.g., Debian, Ubuntu, Alpine, or Red Hat)
    - Programming language packages (e.g., NPM packages or Python packages)
4. Select **Commit changes**.

After you commit changes to the file, a new pipeline starts with this updated Dockerfile. When it’s finished, you can check the results of the new scan.

---

## Scan the Repository with Trivy

You can also scan your repository's files (such as source code and configuration files) for vulnerabilities and misconfigurations using Trivy's repository scanning feature.

To add a pipeline job for repository scanning:

1. In the root directory of your project, open the `.gitlab-ci.yml` file.
2. Add the following job definition:

    ```yaml
    trivy-repo-scan:
      stage: test
      image:
        name: aquasec/trivy:latest
        entrypoint: [""]
      script:
        - trivy repo --exit-code 0 --format table .
        - trivy repo --exit-code 1 --severity CRITICAL .
      allow_failure: true
      artifacts:
        reports:
          sast: gl-sast-report.json
        paths:
          - gl-sast-report.json
    ```

3. Select **Commit changes**.

This job uses the official Trivy image to scan your repository for vulnerabilities. The results will be available in the pipeline's Security tab if any issues are found. For more details, see the [Trivy repository scanning documentation](https://trivy.dev/v0.64/docs/target/repository/).


# did docker in docker service не работает в minikube подумать как исправить