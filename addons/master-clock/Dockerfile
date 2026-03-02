# Master Clock trigger app – zero-dependency Python, stdlib only. UBI9 base.
FROM ubi9/ubi-minimal
RUN microdnf install -y python3 && microdnf clean all
WORKDIR /app
COPY trigger_app.py /app/
CMD ["python3", "trigger_app.py"]
