# Kubernetes target

`deploy/kubernetes/` contains a non-production API Deployment, Service, HPA,
namespace, probes, non-root security context, read-only filesystem, resource
requests, and dropped capabilities. It is design material: the image name,
secret, database, Redis, migrations, ingress, and worker deployment must be
provided by a real release environment. Screen capture is never deployed to
Kubernetes.
