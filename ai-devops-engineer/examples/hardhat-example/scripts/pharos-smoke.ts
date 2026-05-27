import hre from "hardhat";

const { viem } = await hre.network.connect();
const contractName = process.env.PHAROS_CONTRACT_NAME;
const deployedAddress = process.env.PHAROS_DEPLOYED_ADDRESS;
const method = process.env.PHAROS_SMOKE_METHOD;
const args = JSON.parse(process.env.PHAROS_SMOKE_ARGS || "[]");

if (!contractName || !deployedAddress || !method) {
  throw new Error("Missing smoke-test environment variables");
}

const publicClient = await viem.getPublicClient();
const contract = await viem.getContractAt(contractName, deployedAddress);
const hash = await contract.write[method](args);
console.log("Smoke tx:", hash);
const receipt = await publicClient.waitForTransactionReceipt({ hash });
console.log("Smoke status:", receipt.status);
