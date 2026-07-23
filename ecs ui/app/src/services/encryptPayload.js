import CryptoJS from "crypto-js";
import forge from "node-forge";

function getOrCreateRSAKeyPair() {
  const storedPrivateKey = localStorage.getItem("rsa_private_key");
  const storedPublicKey = localStorage.getItem("rsa_public_key");

  if (storedPrivateKey && storedPublicKey) {
    return {
      privateKey: forge.pki.privateKeyFromPem(atob(storedPrivateKey)),
      publicKey: forge.pki.publicKeyFromPem(atob(storedPublicKey)),
    };
  }

  const keypair = forge.pki.rsa.generateKeyPair({ bits: 2048, e: 0x10001 });

  const privateKeyPem = forge.pki.privateKeyToPem(keypair.privateKey);
  const publicKeyPem = forge.pki.publicKeyToPem(keypair.publicKey);

  localStorage.setItem("rsa_private_key", btoa(privateKeyPem));
  localStorage.setItem("rsa_public_key", btoa(publicKeyPem));

  return keypair;
}



export async function encryptPayload(payloadJson) {
  // 1. Generate AES key (256-bit) and IV (128-bit)
  const aesKey = CryptoJS.lib.WordArray.random(32); // 256 bits
  const iv = CryptoJS.lib.WordArray.random(16); // 128 bits

  // 2. AES Encrypt payload
  const encryptedPayload = CryptoJS.AES.encrypt(
    JSON.stringify(payloadJson),
    aesKey,
    {
      iv,
      mode: CryptoJS.mode.CBC,
      padding: CryptoJS.pad.Pkcs7,
    }
  ).toString();

  // 3. Convert AES key to Base64
  const aesKeyBase64 = CryptoJS.enc.Base64.stringify(aesKey);
  const ivBase64 = CryptoJS.enc.Base64.stringify(iv);

  // 4. Generate RSA key pair using forge
  const keypair = getOrCreateRSAKeyPair();

  // const publicKeyPem = forge.pki.publicKeyToPem(keypair.publicKey);
  const privateKeyPem = forge.pki.privateKeyToPem(keypair.privateKey);

  // 5. Encode PEMs to Base64 (removing header/footer and newlines)
  // const rsaPublicKeyBase64 = forge.util.encode64(
  //   forge.util.decode64(
  //     forge.util.encode64(forge.util.encodeUtf8(publicKeyPem))
  //   )
  // );
  const rsaPrivateKeyBase64 = forge.util.encode64(
    forge.util.decode64(
      forge.util.encode64(forge.util.encodeUtf8(privateKeyPem))
    )
  );

  // 6. Encrypt AES key with the public RSA key
  const encryptedAesKey = forge.util.encode64(
    keypair.publicKey.encrypt(forge.util.decode64(aesKeyBase64), "RSA-OAEP")
  );

  return {
    encrypted_data: encryptedPayload,
    aes_key: encryptedAesKey,
    iv: ivBase64,
    private_key: rsaPrivateKeyBase64,
  };
}
