const https = require('node:https');
const fs = require('node:fs');
const crypto = require('node:crypto');

async function configure() {
  const identity = '/var/run/secrets/kubernetes.io/serviceaccount';
  const ca = fs.readFileSync(`${identity}/ca.crt`);
  const token = fs.readFileSync(`${identity}/token`, 'utf8').trim();
  async function request(method, path, body, allowMissing = false) {
    return new Promise((resolve, reject) => {
      const data = body === undefined ? undefined : JSON.stringify(body);
      const req = https.request({
        hostname: 'kubernetes.default.svc', port: 443, method, path, ca,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(data === undefined ? {} : {
            'Content-Type': 'application/merge-patch+json',
            'Content-Length': Buffer.byteLength(data),
          }),
        },
      }, res => {
        let response = '';
        res.setEncoding('utf8');
        res.on('error', reject);
        res.on('data', chunk => {
          response += chunk;
          if (response.length > 1024 * 1024) {
            req.destroy(new Error('Kubernetes response too large'));
          }
        });
        res.on('end', () => {
          if (allowMissing && res.statusCode === 404) return resolve(null);
          if (res.statusCode < 200 || res.statusCode >= 300) {
            return reject(new Error(`Kubernetes ${method} failed (${res.statusCode})`));
          }
          try { resolve(JSON.parse(response)); } catch { reject(new Error('Invalid Kubernetes JSON')); }
        });
      });
      req.on('error', reject);
      req.setTimeout(15000, () => req.destroy(new Error('Kubernetes request timed out')));
      req.end(data);
    });
  }

  const discovery = await request('GET', '/.well-known/openid-configuration');
  const issuer = new URL(discovery.issuer);
  if (issuer.protocol !== 'https:' || issuer.username || issuer.password) {
    throw new Error('Invalid Kubernetes issuer');
  }
  const configMap = await request('GET', '/api/v1/namespaces/ate-system/configmaps/ate-api-authentication');
  const original = configMap.data?.['authentication.yaml'];
  if (typeof original !== 'string') throw new Error('Missing authentication configuration');
  let configuration;
  try {
    configuration = JSON.parse(original);
  } catch {
    // Recognize only the installer's small default YAML document. Custom YAML
    // must be managed by its owner, rather than silently replaced by this helper.
    const generated = original.match(/^actorIdentityJWTProvider: kubernetes\r?\njwtProviders:\r?\n- name: kubernetes\r?\n  issuer: ([^\r\n]+)\r?\n  audiences: \[api\.ate-system\.svc\]\r?\n?$/);
    if (!generated || generated[1] !== discovery.issuer) throw new Error('Unsupported authentication configuration');
    configuration = {
      actorIdentityJWTProvider: 'kubernetes',
      jwtProviders: [{ name: 'kubernetes', issuer: generated[1], audiences: ['api.ate-system.svc'] }],
    };
  }
  if (!Array.isArray(configuration.jwtProviders)) throw new Error('Invalid authentication providers');
  const providers = configuration.jwtProviders.filter(provider => provider.name === 'kubernetes');
  if (providers.length !== 1 || providers[0].issuer !== discovery.issuer) throw new Error('Unexpected Kubernetes issuer');
  Object.assign(providers[0], {
    jwksURI: 'https://kubernetes.default.svc/openid/v1/jwks',
    certificateAuthorityFile: `${identity}/ca.crt`,
    discoveryTokenFile: `${identity}/token`,
  });
  const authentication = JSON.stringify(configuration);
  await request('PATCH', '/api/v1/namespaces/ate-system/configmaps/ate-api-authentication', {
    data: { 'authentication.yaml': authentication },
  });

  // The API reads authentication at startup. A stable hash also repairs partial syncs.
  const deploymentPath = '/apis/apps/v1/namespaces/ate-system/deployments/ate-api-server';
  const deployment = await request('GET', deploymentPath, undefined, true);
  const annotation = 'substrate.ate.dev/authentication-sha256';
  const hash = crypto.createHash('sha256').update(authentication).digest('hex');
  if (deployment && deployment.spec.template.metadata?.annotations?.[annotation] !== hash) {
    await request('PATCH', deploymentPath, {
      spec: { template: { metadata: { annotations: { [annotation]: hash } } } },
    });
  }
  console.log('Substrate Kubernetes JWT authentication configured');
}
configure().catch(() => {
  // Never log response bodies, config contents, or request errors containing credentials.
  console.error('Substrate Kubernetes JWT authentication configuration failed');
  process.exitCode = 1;
});
