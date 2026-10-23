const fs = require('node:fs');
const {EventEmitter} = require('node:events');
const crypto = require('node:crypto');
const vm = require('node:vm');

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const script = fs.readFileSync(input.scriptPath, 'utf8');
const scenario = input.scenario;
const issuer = 'https://cluster.example:6443';
const identity = '/var/run/secrets/kubernetes.io/serviceaccount';
const calls = [];
const logs = [];

function configuredProvider() {
  return {
    name: 'kubernetes',
    issuer,
    audiences: ['api.ate-system.svc'],
    jwksURI: 'https://kubernetes.default.svc/openid/v1/jwks',
    certificateAuthorityFile: `${identity}/ca.crt`,
    discoveryTokenFile: `${identity}/token`,
  };
}

function configuredDocument() {
  return {
    actorIdentityJWTProvider: 'kubernetes',
    jwtProviders: [configuredProvider()],
  };
}

function extendedDocument() {
  return {
    actorIdentityJWTProvider: 'kubernetes',
    jwtProviders: [
      configuredProvider(),
      {
        name: 'external',
        issuer: 'https://other.example',
        audiences: ['external-api'],
        jwksURI: 'https://other.example/keys',
        keep: 'additional provider',
      },
    ],
    additionalSettings: {keep: true},
  };
}

function defaultYaml(value = issuer) {
  return [
    'actorIdentityJWTProvider: kubernetes',
    'jwtProviders:',
    '- name: kubernetes',
    `  issuer: ${value}`,
    '  audiences: [api.ate-system.svc]',
    '',
  ].join('\n');
}

let authenticationYaml;
if (scenario === 'custom-issuer') {
  authenticationYaml = defaultYaml('https://another-issuer.example');
} else if (scenario === 'custom-yaml') {
  authenticationYaml = 'actorIdentityJWTProvider: custom\njwtProviders:\n- name: custom\n';
} else if (scenario === 'repeated-json' || scenario === 'json-other-provider') {
  authenticationYaml = JSON.stringify(extendedDocument());
} else {
  authenticationYaml = defaultYaml();
}

const originalJson = JSON.stringify(extendedDocument());
const originalHash = crypto.createHash('sha256').update(originalJson).digest('hex');
const fakeHttps = {
  request(options, callback) {
    const request = new EventEmitter();
    let timeoutHandler;
    request.destroy = error => queueMicrotask(() => request.emit('error', error));
    request.setTimeout = (milliseconds, handler) => {
      if (milliseconds !== 15000) throw new Error('Request timeout is not bounded');
      timeoutHandler = handler;
    };
    request.end = data => {
      if (options.hostname !== 'kubernetes.default.svc' || options.port !== 443 ||
          options.ca.toString() !== 'test-ca' || options.headers.Authorization !== 'Bearer test-token') {
        throw new Error('Kubernetes request did not use authenticated TLS');
      }
      const call = {method: options.method, path: options.path};
      if (data !== undefined) call.body = JSON.parse(data);
      calls.push(call);
      queueMicrotask(() => {
        if (scenario === 'timeout' && calls.length === 1) {
          timeoutHandler();
          return;
        }
        let statusCode = 200;
        let body = {};
        if (options.path === '/.well-known/openid-configuration') {
          body = {issuer};
        } else if (options.path === '/api/v1/namespaces/ate-system/configmaps/ate-api-authentication') {
          if (options.method === 'GET') {
            body = {data: {'authentication.yaml': authenticationYaml}};
            if (scenario === 'http-failure') statusCode = 403;
          } else {
            authenticationYaml = call.body.data['authentication.yaml'];
          }
        } else if (options.path === '/apis/apps/v1/namespaces/ate-system/deployments/ate-api-server') {
          if (options.method === 'GET') {
            if (scenario === 'first-install') {
              statusCode = 404;
            } else {
              const hash = scenario === 'repeated-json' ? originalHash : 'old-hash';
              body = {spec: {template: {metadata: {annotations: {
                'substrate.ate.dev/authentication-sha256': hash,
              }}}}};
            }
          } else if (scenario === 'deployment-patch-failure') {
            statusCode = 403;
          }
        } else {
          throw new Error(`Unexpected Kubernetes endpoint: ${options.path}`);
        }
        const response = new EventEmitter();
        response.statusCode = statusCode;
        response.setEncoding = () => {};
        callback(response);
        const responseBody = statusCode >= 400 ? {message: 'sensitive-http-response-body'} : body;
        response.emit('data', JSON.stringify(responseBody));
        response.emit('end');
      });
    };
    return request;
  },
};

vm.runInNewContext(script, {
  require(name) {
    if (name === 'node:https') return fakeHttps;
    if (name === 'node:fs') {
      return {
        readFileSync(path) {
          if (path === `${identity}/ca.crt`) return Buffer.from('test-ca');
          if (path === `${identity}/token`) return 'test-token\n';
          throw new Error(`Unexpected filesystem access: ${path}`);
        },
      };
    }
    return require(name);
  },
  URL,
  Buffer,
  process,
  console: {
    log: message => logs.push(message),
    error: message => logs.push(message),
  },
});

process.on('beforeExit', () => {
  process.stdout.write(JSON.stringify({calls, logs, exitCode: process.exitCode || 0}));
});
