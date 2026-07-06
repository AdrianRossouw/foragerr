# mockhub — fixture upstreams for the e2e harness (FRG-PROC-010).
#
# Built FROM the foragerr image purely to reuse its in-image virtualenv (FastAPI
# + uvicorn already installed), so the fixture needs no network install of its
# own and stays byte-pinned to whatever the app was built with. The base image
# ARG is supplied by e2e/run.sh so this always matches the image under test.
ARG BASE_IMAGE=foragerr:e2e
FROM ${BASE_IMAGE}

COPY mock_server.py /opt/mock_server.py

# Plain python entrypoint (bypass the linuxserver privilege-drop entrypoint of
# the base image — mockhub holds no state and needs no /config remap).
ENTRYPOINT ["python", "/opt/mock_server.py"]
