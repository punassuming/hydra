describe("Domain operator journey", () => {
  it("authenticates and reaches the three operator views", () => {
    cy.visit("/");

    cy.get('input[placeholder="prod"]').clear().type("ci");
    cy.get('input[placeholder^="hydra_dom"]').type("ci-domain-token");
    cy.contains("button", "Connect").click();

    cy.contains("Hydra Jobs Control Plane").should("be.visible");
    cy.contains("Queue Health").should("be.visible");

    cy.get(".header-nav-tabs").contains("Observe").click();
    cy.location("pathname").should("eq", "/observe");
    cy.contains("Job Status").should("be.visible");

    cy.get(".header-nav-tabs").contains("Workers").click();
    cy.location("pathname").should("eq", "/workers");
    cy.contains("Workers Online").should("be.visible");
  });
});
